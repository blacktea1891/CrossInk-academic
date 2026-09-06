#pragma once

#include <HalStorage.h>
#include <Logging.h>
#include <stdint.h>

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <string>

// Streaming cache writer for 2-bit pixels (4 levels). Packs 4 pixels per byte,
// MSB first.
//
// The .pxc file is written incrementally in small row bands rather than holding
// the whole decoded image in one heap buffer. A full-page image (e.g. 482x728)
// needs ~88KB packed, which will not fit alongside the ~20KB JPEG decoder on a
// fragmented 380KB heap (free heap is routinely ~55KB on an image page). When
// the cache cannot be written, every render pass re-decodes the JPEG from
// scratch; an anti-aliased image page renders ~14 times (BW + AA restore + two
// grayscale planes x ~6 strips), so a 2s decode becomes a ~30s freeze / watchdog
// reset. Streaming keeps the working set to a single MCU-row band, so caching
// succeeds and the image is decoded exactly once.
//
// Correctness relies on decoders delivering output in raster order. Consecutive
// source blocks/rows map to contiguous, non-overlapping destination row ranges,
// so once the next block no longer fits in the current band, every row before it
// is final and can be flushed to disk in one contiguous write.
struct PixelCache {
  uint8_t* buffer;   // band buffer: (bandRows + 1) rows; last row kept zeroed
  uint8_t* zeroRow;  // points at the spare zeroed row, for gap/clip fill
  int width;
  int height;
  int bytesPerRow;
  int originX;        // config.x - to convert screen coords to cache coords
  int originY;        // config.y
  int bandRows;       // rows held in the band buffer
  int maxBlockRows;   // max destination rows one decoder callback/block can emit
  int bandStart;      // image-local row index of band buffer row 0
  int flushedRows;    // image-local rows already written to file
  HalFile file;
  std::string cachePathStr;
  bool ok;

  PixelCache()
      : buffer(nullptr),
        zeroRow(nullptr),
        width(0),
        height(0),
        bytesPerRow(0),
        originX(0),
        originY(0),
        bandRows(0),
        maxBlockRows(1),
        bandStart(0),
        flushedRows(0),
        ok(false) {}
  PixelCache(const PixelCache&) = delete;
  PixelCache& operator=(const PixelCache&) = delete;

  static constexpr int MIN_BAND_ROWS = 16;
  static constexpr size_t MAX_BAND_BYTES = 24 * 1024;  // band working-set ceiling

  // Open the cache file, write the header, and allocate a band buffer big enough
  // to hold the tallest single decode block (maxBlockDstRows output rows).
  bool begin(const std::string& cachePath, int w, int h, int ox, int oy, int maxBlockDstRows) {
    width = w;
    height = h;
    originX = ox;
    originY = oy;
    bytesPerRow = (w + 3) / 4;  // 2 bits per pixel, 4 pixels per byte
    bandStart = 0;
    flushedRows = 0;
    ok = false;
    maxBlockRows = std::max(1, maxBlockDstRows);

    int wantRows = maxBlockRows + 2;
    if (wantRows < MIN_BAND_ROWS) wantRows = MIN_BAND_ROWS;
    if (wantRows > h) wantRows = h;

    size_t maxRowsByMem = MAX_BAND_BYTES / (size_t)bytesPerRow;
    if (maxRowsByMem < 1) maxRowsByMem = 1;
    if ((size_t)wantRows > maxRowsByMem) wantRows = (int)maxRowsByMem;

    // A single decode block must fit inside the band, otherwise streaming would
    // drop rows. This only fails for pathological upscales that could not be
    // cached at all; fall back to the no-cache path.
    if (wantRows < maxBlockRows) {
      LOG_ERR("IMG", "Cache band too small (%d < %d rows) for %dx%d", wantRows, maxBlockRows, w, h);
      return false;
    }
    bandRows = wantRows;

    const size_t bufSize = (size_t)(bandRows + 1) * bytesPerRow;  // +1 spare zero row
    buffer = (uint8_t*)malloc(bufSize);
    if (!buffer) {
      LOG_ERR("IMG", "OOM cache band: %u bytes", (unsigned)bufSize);
      return false;
    }
    memset(buffer, 0, bufSize);
    zeroRow = buffer + (size_t)bandRows * bytesPerRow;

    if (!Storage.openFileForWrite("IMG", cachePath, file)) {
      LOG_ERR("IMG", "Failed to open cache file for writing: %s", cachePath.c_str());
      free(buffer);
      buffer = nullptr;
      return false;
    }
    cachePathStr = cachePath;

    uint16_t w16 = (uint16_t)w;
    uint16_t h16 = (uint16_t)h;
    if (file.write(&w16, 2) != 2 || file.write(&h16, 2) != 2) {
      LOG_ERR("IMG", "Failed to write cache header: %s", cachePath.c_str());
      abort();
      return false;
    }

    ok = true;
    return true;
  }

  // Advance the streaming band when the next decoder block would no longer fit.
  // Keeping rows resident until the band fills is important for PNG: its callback
  // arrives one output row at a time, and eagerly flushing on every callback turns
  // a 700-row image into ~700 tiny SD writes. With a 16+ row band we instead make
  // a few dozen contiguous writes while preserving the same small RAM footprint.
  bool advanceTo(int newTopRow) {
    if (!ok) return false;
    if (newTopRow <= bandStart) return true;
    if (newTopRow > height) newTopRow = height;

    const int bandEnd = bandStart + bandRows;
    if (newTopRow < height && newTopRow + maxBlockRows <= bandEnd) {
      return true;
    }

    const int rowsToFlush = newTopRow - bandStart;
    const int bufferedRows = std::min(rowsToFlush, bandRows);
    if (bufferedRows > 0) {
      const size_t bytes = (size_t)bufferedRows * bytesPerRow;
      if (file.write(buffer, bytes) != bytes) {
        LOG_ERR("IMG", "Cache write error at row %d", bandStart);
        ok = false;
        return false;
      }
    }

    // If the caller jumped farther than one band (normally only clipping/gaps),
    // preserve the old behavior by zero-filling the skipped rows.
    for (int r = bufferedRows; r < rowsToFlush; ++r) {
      if (file.write(zeroRow, (size_t)bytesPerRow) != (size_t)bytesPerRow) {
        LOG_ERR("IMG", "Cache write error at row %d", bandStart + r);
        ok = false;
        return false;
      }
    }

    flushedRows = newTopRow;
    bandStart = newTopRow;
    memset(buffer, 0, (size_t)bandRows * bytesPerRow);  // fresh band (gaps stay black)
    return true;
  }

  // Flush the final band and zero-fill any rows never covered (image clipped by
  // the screen), then close the file.
  bool finalize() {
    if (!ok) {
      abort();
      return false;
    }
    if (!advanceTo(height)) {
      abort();
      return false;
    }
    file.close();
    ok = false;  // file handed off; nothing left to clean up
    return true;
  }

  // Drop a partial/failed cache so a later decode re-creates it cleanly.
  void abort() {
    if (file.isOpen()) file.close();
    if (!cachePathStr.empty()) {
      Storage.remove(cachePathStr.c_str());
    }
    ok = false;
  }

  ~PixelCache() {
    if (file.isOpen()) {
      // The file is still open, so neither finalize() nor abort() ran, or a
      // mid-stream write failed (advanceTo() cleared ok but left the file open).
      // Drop the partial cache so we leave no corrupt file behind.
      abort();
    }
    if (buffer) {
      free(buffer);
      buffer = nullptr;
    }
  }
};
