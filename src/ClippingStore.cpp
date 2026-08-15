#include "ClippingStore.h"

#include <Arduino.h>
#include <HalStorage.h>
#include <Logging.h>
#include <Serialization.h>
#include <uzlib.h>

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <utility>

#include "AnnotationTagStore.h"
#include "KOReaderDocumentId.h"
#include "util/AtomicFile.h"

namespace {
constexpr uint8_t LEGACY_VERSION = 1;
constexpr uint8_t TEXT_OFFSET_VERSION = 2;
constexpr uint8_t LAYOUT_SIGNATURE_VERSION = 3;
constexpr uint8_t VERSION = 4;
constexpr uint8_t WRITE_VERSION = LAYOUT_SIGNATURE_VERSION;
constexpr uint8_t TAG_SIDECAR_VERSION = 1;
constexpr uint16_t DOWNGRADE_TEXT_MAX = 512;
constexpr size_t INITIAL_CLIPPING_RESERVE = 4;
constexpr char CLIPPINGS_DIR[] = "/.crosspoint/clippings";
constexpr size_t TEXT_COPY_BUFFER_SIZE = 128;

struct ClippingTagRecord {
  uint64_t fingerprint = 0;
  uint16_t tagId = 0;
  uint32_t textOffset = 0;
  uint16_t textLength = 0;
};

struct ClippingFileHeader {
  std::string title;
  std::string author;
  std::string path;
  std::string bookType;
  uint16_t count = 0;
};

std::string storeFilePathForBook(const std::string& filePath, const std::string& bookType) {
  const uint32_t crc = uzlib_crc32(filePath.data(), static_cast<unsigned int>(filePath.size()), 0);
  return std::string(CLIPPINGS_DIR) + "/" + bookType + "_" + std::to_string(crc) + ".bin";
}

std::string tagSidecarPath(const std::string& primaryPath) { return primaryPath + ".tags"; }

void hashBytes(uint32_t& low, uint32_t& high, const void* data, const size_t size) {
  low = uzlib_crc32(data, static_cast<unsigned int>(size), low);
  high = uzlib_crc32(data, static_cast<unsigned int>(size), high);
}

template <typename T>
void hashValue(uint32_t& low, uint32_t& high, const T& value) {
  hashBytes(low, high, &value, sizeof(value));
}

bool clippingFingerprint(FsFile& primary, const Clipping& clipping, const uint32_t textOffset,
                         const uint16_t textLength, uint64_t& out) {
  uint32_t low = 0;
  uint32_t high = 0x9e3779b9U;
  hashValue(low, high, clipping.spineIndex);
  hashValue(low, high, clipping.startWordIndex);
  hashValue(low, high, clipping.endWordIndex);
  hashValue(low, high, clipping.wordCount);
  hashValue(low, high, clipping.paragraphIndex);
  hashValue(low, high, clipping.timestamp);
  hashBytes(low, high, clipping.chapterTitle, sizeof(clipping.chapterTitle));
  hashValue(low, high, textLength);

  if (textLength > 0) {
    if (!primary.seek(textOffset)) return false;
    std::array<uint8_t, TEXT_COPY_BUFFER_SIZE> buffer{};
    uint16_t remaining = textLength;
    while (remaining > 0) {
      const size_t chunk = std::min<size_t>(remaining, buffer.size());
      if (primary.read(buffer.data(), chunk) != static_cast<int>(chunk)) return false;
      hashBytes(low, high, buffer.data(), chunk);
      remaining = static_cast<uint16_t>(remaining - chunk);
    }
  }
  out = (static_cast<uint64_t>(high) << 32U) | low;
  return true;
}

void copyBounded(char* dst, const size_t dstSize, const char* src) {
  if (dstSize == 0) return;
  if (!src) src = "";
  snprintf(dst, dstSize, "%s", src);
}

bool readClippingFileHeader(const std::string& fullPath, const char* name, ClippingFileHeader& header) {
  FsFile f;
  if (!Storage.openFileForRead("CLIP", fullPath, f)) {
    return false;
  }

  uint8_t version = 0;
  uint16_t count = 0;
  if (!serialization::tryReadPod(f, version) ||
      (version != LEGACY_VERSION && version != TEXT_OFFSET_VERSION && version != LAYOUT_SIGNATURE_VERSION &&
       version != VERSION) ||
      !serialization::tryReadPod(f, count) || !serialization::tryReadString(f, header.title) ||
      !serialization::tryReadString(f, header.author) || !serialization::tryReadString(f, header.path)) {
    f.close();
    return false;
  }
  if (version >= VERSION) {
    std::string documentId;
    if (!serialization::tryReadString(f, documentId)) {
      f.close();
      return false;
    }
  }
  f.close();

  if (count > CLIPPING_MAX_PER_BOOK) {
    return false;
  }
  header.count = count;
  header.bookType = "epub";
  const std::string nameStr = name ? name : "";
  const size_t underscorePos = nameStr.find('_');
  if (underscorePos != std::string::npos) {
    header.bookType = nameStr.substr(0, underscorePos);
  }
  return true;
}

}  // namespace

ClippingStore ClippingStore::instance;

bool ClippingStore::loadForBook(const std::string& filePath, const std::string& title, const std::string& author,
                                const std::string& bookType) {
  return loadForBook(filePath, title, author, bookType, KOReaderDocumentId::calculate(filePath));
}

bool ClippingStore::loadForBook(const std::string& filePath, const std::string& title, const std::string& author,
                                const std::string& bookType, const std::string& documentId) {
  if (bookType != "epub") {
    LOG_ERR("CLIP", "Unknown clipping book type: %s", bookType.c_str());
    return false;
  }

  bookFilePath = filePath;
  bookTitle = title;
  bookAuthor = author;
  bookDocumentId = documentId;
  dirty = false;
  ready = false;
  clippings.clear();
  if (clippings.capacity() < INITIAL_CLIPPING_RESERVE) {
    clippings.reserve(INITIAL_CLIPPING_RESERVE);
  }

  storeFilePath = storeFilePathForBook(filePath, bookType);
  sourceFilePath.clear();
  sidecarSourceFilePath.clear();
  const std::string backupPath = AtomicFile::backupPath(storeFilePath);
  const bool hasCurrent = Storage.exists(storeFilePath.c_str());
  const bool hasBackup = Storage.exists(backupPath.c_str());
  if (!hasCurrent && !hasBackup) {
    sourceFilePath = storeFilePath;
    ready = true;
    return true;
  }
  uint8_t loadedVersion = 0;
  if (hasCurrent && readFromFile(storeFilePath, clippings, &loadedVersion)) {
    sourceFilePath = storeFilePath;
    ready = true;
    if (!loadTagSidecar()) {
      ready = false;
      LOG_ERR("CLIP", "Clippings loaded in read-only compatibility mode because their tag sidecar is invalid");
      return false;
    }
    if (loadedVersion == VERSION) {
      dirty = true;
      if (!saveToFile()) LOG_ERR("CLIP", "Failed to migrate clipping store to downgrade-compatible format");
    }
    return true;
  }
  loadedVersion = 0;
  if (hasBackup && readFromFile(backupPath, clippings, &loadedVersion)) {
    if (hasCurrent && !Storage.remove(storeFilePath.c_str())) {
      LOG_ERR("CLIP", "Recovered clippings but could not remove corrupt current file: %s", storeFilePath.c_str());
      clippings.clear();
      return false;
    }
    sourceFilePath = backupPath;
    ready = true;
    if (!loadTagSidecar()) {
      ready = false;
      LOG_ERR("CLIP", "Recovered clippings are read-only because their tag sidecar is invalid");
      return false;
    }
    if (loadedVersion == VERSION) {
      dirty = true;
      if (!saveToFile()) LOG_ERR("CLIP", "Failed to migrate recovered clipping store");
    }
    LOG_INF("CLIP", "Loaded clippings from backup: %s", backupPath.c_str());
    return true;
  }
  clippings.clear();
  return false;
}

void ClippingStore::unload() {
  if (dirty && ready) saveToFile();
  clippings.clear();
  bookFilePath.clear();
  bookTitle.clear();
  bookAuthor.clear();
  bookDocumentId.clear();
  storeFilePath.clear();
  sourceFilePath.clear();
  sidecarSourceFilePath.clear();
  dirty = false;
  ready = false;
}

ClippingStore::AddResult ClippingStore::addClipping(const uint16_t spineIndex, const uint16_t startPage,
                                                    const uint16_t endPage, const uint16_t pageCount,
                                                    const uint16_t startWordIndex, const uint16_t endWordIndex,
                                                    const uint16_t wordCount, const char* chapterTitle,
                                                    const uint16_t paragraphIndex, const std::string& text,
                                                    const uint32_t layoutSignature, const uint16_t tagId) {
  if (!ready) {
    LOG_ERR("CLIP", "Refusing to add a clipping before a successful load");
    return AddResult::SaveFailed;
  }
  if (clippings.size() >= CLIPPING_MAX_PER_BOOK) {
    LOG_ERR("CLIP", "Clipping limit (%u) reached", CLIPPING_MAX_PER_BOOK);
    return AddResult::LimitReached;
  }
  if (text.size() > CLIPPING_TEXT_MAX) {
    LOG_ERR("CLIP", "Clipping text length %u exceeds max %u", static_cast<unsigned>(text.size()),
            static_cast<unsigned>(CLIPPING_TEXT_MAX));
    return AddResult::TextTooLong;
  }

  Clipping clipping;
  clipping.spineIndex = spineIndex;
  clipping.startPage = startPage;
  clipping.endPage = endPage;
  clipping.pageCount = std::max<uint16_t>(1, pageCount);
  clipping.startWordIndex = startWordIndex;
  clipping.endWordIndex = endWordIndex;
  clipping.wordCount = wordCount;
  clipping.paragraphIndex = paragraphIndex;
  clipping.timestamp = static_cast<uint32_t>(millis() / 1000UL);
  clipping.layoutSignature = layoutSignature;
  clipping.tagId = tagId;
  copyBounded(clipping.chapterTitle, sizeof(clipping.chapterTitle), chapterTitle);
  clipping.textLength = static_cast<uint16_t>(text.size());

  clippings.push_back(std::move(clipping));
  dirty = true;
  if (!writeToFile(&text, clippings.size() - 1)) {
    clippings.pop_back();
    dirty = true;
    return AddResult::SaveFailed;
  }
  dirty = false;
  return AddResult::Added;
}

bool ClippingStore::stampMissingLayoutSignature(const uint32_t layoutSignature) {
  if (!ready) return false;
  if (layoutSignature == 0) return true;

  bool changed = false;
  for (Clipping& clipping : clippings) {
    if (clipping.layoutSignature == 0) {
      clipping.layoutSignature = layoutSignature;
      changed = true;
    }
  }
  if (!changed) return true;

  dirty = true;
  if (writeToFile()) {
    dirty = false;
    return true;
  }
  return false;
}

bool ClippingStore::removeClippingAt(const size_t index) {
  if (!ready) return false;
  if (index >= clippings.size()) return false;
  Clipping clipping = std::move(clippings[index]);
  clippings.erase(clippings.begin() + index);
  dirty = true;
  if (!saveToFile()) {
    clippings.insert(clippings.begin() + index, std::move(clipping));
    dirty = true;
    return false;
  }
  return true;
}

bool ClippingStore::hasClippingForPage(const uint16_t spineIndex, const uint16_t page) const {
  return std::any_of(clippings.begin(), clippings.end(), [&](const Clipping& clipping) {
    return clipping.spineIndex == spineIndex && page >= clipping.startPage && page <= clipping.endPage;
  });
}

const Clipping* ClippingStore::clippingAt(const size_t index) const {
  if (index >= clippings.size()) return nullptr;
  return &clippings[index];
}

bool ClippingStore::readClippingText(const size_t index, std::string& out) const {
  const Clipping* clipping = clippingAt(index);
  if (!clipping) return false;
  return readClippingText(*clipping, out);
}

bool ClippingStore::readClippingText(const Clipping& clipping, std::string& out) const {
  out.clear();
  if (clipping.textLength == 0) return true;

  const std::string& textPath = clipping.textInSidecar ? sidecarSourceFilePath : sourceFilePath;
  if (textPath.empty()) return false;
  FsFile f;
  if (!Storage.openFileForRead("CLIP", textPath, f)) {
    return false;
  }
  if (!f.seek(clipping.textOffset)) {
    f.close();
    LOG_ERR("CLIP", "Failed to seek clipping text at %u: %s", clipping.textOffset, textPath.c_str());
    return false;
  }
  out.resize(clipping.textLength);
  const int expected = static_cast<int>(clipping.textLength);
  const bool ok = f.read(&out[0], clipping.textLength) == expected;
  f.close();
  if (!ok) {
    out.clear();
    LOG_ERR("CLIP", "Failed to read clipping text at %u: %s", clipping.textOffset, textPath.c_str());
  }
  return ok;
}

bool ClippingStore::clearUnknownTagIds() {
  if (!ready || !ANNOTATION_TAGS.isReady()) return false;
  bool changed = false;
  for (Clipping& clipping : clippings) {
    if (clipping.tagId != 0 && !ANNOTATION_TAGS.nameForId(clipping.tagId)) {
      clipping.tagId = 0;
      changed = true;
    }
  }
  if (!changed) return true;
  dirty = true;
  return saveToFile();
}

bool ClippingStore::saveToFile() {
  if (!ready) return false;
  if (!dirty) return true;
  if (writeToFile()) {
    dirty = false;
    return true;
  }
  return false;
}

void ClippingStore::clearAll() {
  if (!ready) return;
  clippings.clear();
  dirty = false;
  const std::string sidecarPath = tagSidecarPath(storeFilePath);
  const std::array<std::string, 6> paths = {
      storeFilePath,
      AtomicFile::temporaryPath(storeFilePath),
      AtomicFile::backupPath(storeFilePath),
      sidecarPath,
      AtomicFile::temporaryPath(sidecarPath),
      AtomicFile::backupPath(sidecarPath),
  };
  for (const std::string& path : paths) {
    if (Storage.exists(path.c_str())) Storage.remove(path.c_str());
  }
  sourceFilePath = storeFilePath;
  sidecarSourceFilePath = sidecarPath;
}

bool ClippingStore::readFromFile() {
  const bool ok = readFromFile(storeFilePath, clippings);
  if (ok) sourceFilePath = storeFilePath;
  return ok;
}

bool ClippingStore::readFromFile(const std::string& path, std::vector<Clipping>& out, uint8_t* loadedVersion) const {
  out.clear();
  FsFile f;
  if (!Storage.openFileForRead("CLIP", path, f)) {
    return false;
  }

  uint8_t version = 0;
  uint16_t count = 0;
  std::string title;
  std::string author;
  std::string storedPath;
  if (!serialization::tryReadPod(f, version) ||
      (version != LEGACY_VERSION && version != TEXT_OFFSET_VERSION && version != LAYOUT_SIGNATURE_VERSION &&
       version != VERSION) ||
      !serialization::tryReadPod(f, count) || !serialization::tryReadString(f, title) ||
      !serialization::tryReadString(f, author) || !serialization::tryReadString(f, storedPath)) {
    f.close();
    LOG_ERR("CLIP", "Failed to read clipping header: %s", path.c_str());
    return false;
  }
  if (loadedVersion) *loadedVersion = version;

  if (storedPath != bookFilePath) {
    LOG_ERR("CLIP", "Clipping file path mismatch, ignoring stale file: %s", path.c_str());
    f.close();
    return false;
  }

  std::string storedDocumentId;
  if (version >= VERSION && !serialization::tryReadString(f, storedDocumentId)) {
    f.close();
    LOG_ERR("CLIP", "Clipping file missing document identity: %s", path.c_str());
    return false;
  }
  if (!storedDocumentId.empty() && storedDocumentId != bookDocumentId) {
    LOG_ERR("CLIP", "Clipping file document identity mismatch, ignoring stale file: %s", path.c_str());
    f.close();
    return false;
  }

  if (count > CLIPPING_MAX_PER_BOOK) {
    LOG_ERR("CLIP", "Clipping count %u exceeds max, file may be corrupt: %s", count, path.c_str());
    f.close();
    return false;
  }

  out.reserve(count);
  for (uint16_t i = 0; i < count; ++i) {
    Clipping clipping;
    if (!serialization::tryReadPod(f, clipping.spineIndex) || !serialization::tryReadPod(f, clipping.startPage) ||
        !serialization::tryReadPod(f, clipping.endPage) || !serialization::tryReadPod(f, clipping.pageCount) ||
        !serialization::tryReadPod(f, clipping.startWordIndex) ||
        !serialization::tryReadPod(f, clipping.endWordIndex) || !serialization::tryReadPod(f, clipping.wordCount) ||
        !serialization::tryReadPod(f, clipping.paragraphIndex) || !serialization::tryReadPod(f, clipping.timestamp)) {
      f.close();
      LOG_ERR("CLIP", "Clipping file truncated at record %u: %s", i, path.c_str());
      return false;
    }
    if (version >= LAYOUT_SIGNATURE_VERSION && !serialization::tryReadPod(f, clipping.layoutSignature)) {
      f.close();
      LOG_ERR("CLIP", "Clipping file truncated at layout signature, record %u: %s", i, path.c_str());
      return false;
    }
    if (version >= VERSION && !serialization::tryReadPod(f, clipping.tagId)) {
      f.close();
      LOG_ERR("CLIP", "Clipping file truncated at tag ID, record %u: %s", i, path.c_str());
      return false;
    }
    if (f.read(reinterpret_cast<uint8_t*>(clipping.chapterTitle), sizeof(clipping.chapterTitle)) !=
        sizeof(clipping.chapterTitle)) {
      f.close();
      LOG_ERR("CLIP", "Clipping file truncated at chapter title, record %u: %s", i, path.c_str());
      return false;
    }
    clipping.chapterTitle[sizeof(clipping.chapterTitle) - 1] = '\0';
    if (version == LEGACY_VERSION) {
      uint32_t textLen = 0;
      if (!serialization::tryReadPod(f, textLen)) {
        f.close();
        LOG_ERR("CLIP", "Clipping file truncated at text length, record %u: %s", i, path.c_str());
        return false;
      }
      clipping.textOffset = static_cast<uint32_t>(f.position());
      clipping.textLength = static_cast<uint16_t>(std::min<uint32_t>(textLen, CLIPPING_TEXT_MAX));
      if (textLen > 0 && !f.seekCur(textLen)) {
        f.close();
        LOG_ERR("CLIP", "Clipping file truncated at text, record %u: %s", i, path.c_str());
        return false;
      }
    } else {
      if (!serialization::tryReadPod(f, clipping.textLength)) {
        f.close();
        LOG_ERR("CLIP", "Clipping file truncated at text length, record %u: %s", i, path.c_str());
        return false;
      }
      if (clipping.textLength > CLIPPING_TEXT_MAX) {
        f.close();
        LOG_ERR("CLIP", "Clipping text length %u exceeds max, record %u: %s", clipping.textLength, i, path.c_str());
        return false;
      }
      clipping.textOffset = static_cast<uint32_t>(f.position());
      if (clipping.textLength > 0 && !f.seekCur(clipping.textLength)) {
        f.close();
        LOG_ERR("CLIP", "Clipping file truncated at text, record %u: %s", i, path.c_str());
        return false;
      }
    }
    out.push_back(std::move(clipping));
  }

  f.close();
  return true;
}

bool ClippingStore::loadTagSidecar() {
  const std::string currentPath = tagSidecarPath(storeFilePath);
  const std::string backupPath = AtomicFile::backupPath(currentPath);
  if (!Storage.exists(currentPath.c_str()) && !Storage.exists(backupPath.c_str())) return true;

  std::vector<uint64_t> fingerprints;
  fingerprints.reserve(clippings.size());
  FsFile primary;
  if (!Storage.openFileForRead("CLIP", sourceFilePath, primary)) return false;
  for (const Clipping& clipping : clippings) {
    uint64_t fingerprint = 0;
    if (!clippingFingerprint(primary, clipping, clipping.textOffset, clipping.textLength, fingerprint)) {
      primary.close();
      LOG_ERR("CLIP", "Failed to fingerprint clipping text for tag recovery");
      return false;
    }
    fingerprints.push_back(fingerprint);
  }
  primary.close();

  const auto readSidecar = [&](const std::string& path, std::vector<ClippingTagRecord>& records) {
    FsFile file;
    if (!Storage.openFileForRead("CLIP", path, file)) return false;
    uint8_t version = 0;
    uint16_t count = 0;
    std::string storedPath;
    std::string documentId;
    if (!serialization::tryReadPod(file, version) || version != TAG_SIDECAR_VERSION ||
        !serialization::tryReadPod(file, count) || count > CLIPPING_MAX_PER_BOOK ||
        !serialization::tryReadString(file, storedPath) || !serialization::tryReadString(file, documentId) ||
        storedPath != bookFilePath || (!documentId.empty() && documentId != bookDocumentId)) {
      file.close();
      return false;
    }

    records.clear();
    records.reserve(count);
    for (uint16_t i = 0; i < count; ++i) {
      ClippingTagRecord record;
      if (!serialization::tryReadPod(file, record.fingerprint) || !serialization::tryReadPod(file, record.tagId) ||
          !serialization::tryReadPod(file, record.textLength) || record.textLength > CLIPPING_TEXT_MAX) {
        file.close();
        return false;
      }
      record.textOffset = static_cast<uint32_t>(file.position());
      if (record.textLength > 0 && !file.seekCur(record.textLength)) {
        file.close();
        return false;
      }
      records.push_back(record);
    }
    file.close();
    return true;
  };

  const auto matchRecords = [&](const std::vector<ClippingTagRecord>& records, std::vector<size_t>& matches) {
    std::vector<bool> matched(fingerprints.size(), false);
    matches.clear();
    matches.reserve(records.size());
    size_t matchCount = 0;
    for (const ClippingTagRecord& record : records) {
      size_t matchIndex = fingerprints.size();
      for (size_t i = 0; i < fingerprints.size(); ++i) {
        if (!matched[i] && fingerprints[i] == record.fingerprint) {
          matched[i] = true;
          matchIndex = i;
          break;
        }
      }
      matches.push_back(matchIndex);
      if (matchIndex != fingerprints.size()) ++matchCount;
    }
    return matchCount;
  };

  std::vector<ClippingTagRecord> currentRecords;
  std::vector<ClippingTagRecord> backupRecords;
  const bool currentValid = Storage.exists(currentPath.c_str()) && readSidecar(currentPath, currentRecords);
  const bool backupValid = Storage.exists(backupPath.c_str()) && readSidecar(backupPath, backupRecords);
  if (!currentValid && !backupValid) {
    LOG_ERR("CLIP", "Clipping tag sidecar is invalid; clippings remain available with compatibility previews");
    return false;
  }

  std::vector<size_t> currentMatches;
  std::vector<size_t> backupMatches;
  const size_t currentScore = currentValid ? matchRecords(currentRecords, currentMatches) : 0;
  const size_t backupScore = backupValid ? matchRecords(backupRecords, backupMatches) : 0;
  const bool useBackup = backupValid && (!currentValid || backupScore > currentScore);
  const std::vector<ClippingTagRecord>& records = useBackup ? backupRecords : currentRecords;
  const std::vector<size_t>& matches = useBackup ? backupMatches : currentMatches;
  const std::string& selectedPath = useBackup ? backupPath : currentPath;
  sidecarSourceFilePath = selectedPath;

  for (size_t i = 0; i < records.size(); ++i) {
    if (matches[i] == fingerprints.size()) continue;
    Clipping& clipping = clippings[matches[i]];
    clipping.tagId = records[i].tagId;
    clipping.textOffset = records[i].textOffset;
    clipping.textLength = records[i].textLength;
    clipping.textInSidecar = true;
  }

  if (useBackup) {
    if (Storage.exists(currentPath.c_str()) && !Storage.remove(currentPath.c_str())) {
      LOG_ERR("CLIP", "Recovered clipping tags but could not remove invalid current sidecar");
      return false;
    }
    LOG_INF("CLIP", "Loaded clipping tags from backup: %s", backupPath.c_str());
    return true;
  }
  return true;
}

bool ClippingStore::writeTagSidecarTemp(const std::string& primaryTempPath,
                                        const std::vector<uint32_t>& previewOffsets,
                                        const std::vector<uint16_t>& previewLengths,
                                        const std::string* replacementText, const size_t replacementIndex,
                                        std::vector<uint32_t>& sidecarTextOffsets,
                                        std::vector<uint16_t>& sidecarTextLengths) const {
  const std::string sidecarPath = tagSidecarPath(storeFilePath);
  const std::string tempPath = AtomicFile::temporaryPath(sidecarPath);
  FsFile primary;
  if (!Storage.openFileForRead("CLIP", primaryTempPath, primary)) return false;

  FsFile file;
  if (!Storage.openFileForWrite("CLIP", tempPath, file)) {
    primary.close();
    return false;
  }
  const uint16_t count = static_cast<uint16_t>(clippings.size());
  bool ok = serialization::tryWritePod(file, TAG_SIDECAR_VERSION) && serialization::tryWritePod(file, count) &&
            serialization::tryWriteString(file, bookFilePath) &&
            serialization::tryWriteString(file, bookDocumentId);
  sidecarTextOffsets.clear();
  sidecarTextLengths.clear();
  sidecarTextOffsets.reserve(count);
  sidecarTextLengths.reserve(count);
  std::string fullText;
  fullText.reserve(CLIPPING_TEXT_INITIAL_RESERVE);
  for (uint16_t i = 0; ok && i < count; ++i) {
    ClippingTagRecord record;
    record.tagId = clippings[i].tagId;
    ok = clippingFingerprint(primary, clippings[i], previewOffsets[i], previewLengths[i], record.fingerprint);
    const bool useReplacement = replacementText && i == replacementIndex;
    if (ok && useReplacement) {
      fullText = *replacementText;
    } else if (ok && !readClippingText(clippings[i], fullText)) {
      ok = false;
    }
    record.textLength = static_cast<uint16_t>(fullText.size());
    ok = ok && fullText.size() <= CLIPPING_TEXT_MAX && serialization::tryWritePod(file, record.fingerprint) &&
         serialization::tryWritePod(file, record.tagId) && serialization::tryWritePod(file, record.textLength);
    record.textOffset = static_cast<uint32_t>(file.position());
    if (ok && record.textLength > 0) {
      ok = file.write(reinterpret_cast<const uint8_t*>(fullText.data()), record.textLength) == record.textLength;
    }
    if (ok) {
      sidecarTextOffsets.push_back(record.textOffset);
      sidecarTextLengths.push_back(record.textLength);
    }
  }
  ok = ok && file.sync();
  primary.close();
  file.close();
  if (!ok) {
    Storage.remove(tempPath.c_str());
    LOG_ERR("CLIP", "Failed to write clipping tag sidecar");
  }
  return ok;
}

bool ClippingStore::writeToFile(const std::string* replacementText, const size_t replacementIndex) {
  if (!ready) {
    LOG_ERR("CLIP", "Refusing to save clippings before a successful load");
    return false;
  }
  if (replacementText && replacementText->size() > CLIPPING_TEXT_MAX) {
    LOG_ERR("CLIP", "Refusing to write oversized clipping text");
    return false;
  }
  Storage.mkdir("/.crosspoint");
  Storage.mkdir(CLIPPINGS_DIR);

  const std::string tmpPath = AtomicFile::temporaryPath(storeFilePath);
  if (!AtomicFile::prepare(storeFilePath, "CLIP")) return false;
  const std::string sidecarPath = tagSidecarPath(storeFilePath);
  if (!AtomicFile::prepare(sidecarPath, "CLIP")) return false;

  FsFile f = Storage.open(tmpPath.c_str(), O_WRONLY | O_CREAT | O_TRUNC);
  if (!f) {
    LOG_ERR("CLIP", "Failed to open clipping temp file for write: %s", tmpPath.c_str());
    return false;
  }

  const uint16_t count = static_cast<uint16_t>(std::min<size_t>(clippings.size(), CLIPPING_MAX_PER_BOOK));
  std::vector<uint32_t> previewOffsets;
  previewOffsets.reserve(count);
  std::vector<uint16_t> previewLengths;
  previewLengths.reserve(count);
  if (!serialization::tryWritePod(f, WRITE_VERSION) || !serialization::tryWritePod(f, count) ||
      !serialization::tryWriteString(f, bookTitle) || !serialization::tryWriteString(f, bookAuthor) ||
      !serialization::tryWriteString(f, bookFilePath)) {
    LOG_ERR("CLIP", "Failed to write clipping header: %s", tmpPath.c_str());
    f.close();
    Storage.remove(tmpPath.c_str());
    return false;
  }

  std::string fullText;
  fullText.reserve(CLIPPING_TEXT_INITIAL_RESERVE);
  for (uint16_t i = 0; i < count; ++i) {
    const Clipping& clipping = clippings[i];
    if (!serialization::tryWritePod(f, clipping.spineIndex) || !serialization::tryWritePod(f, clipping.startPage) ||
        !serialization::tryWritePod(f, clipping.endPage) || !serialization::tryWritePod(f, clipping.pageCount) ||
        !serialization::tryWritePod(f, clipping.startWordIndex) ||
        !serialization::tryWritePod(f, clipping.endWordIndex) || !serialization::tryWritePod(f, clipping.wordCount) ||
        !serialization::tryWritePod(f, clipping.paragraphIndex) || !serialization::tryWritePod(f, clipping.timestamp) ||
        !serialization::tryWritePod(f, clipping.layoutSignature) ||
        f.write(reinterpret_cast<const uint8_t*>(clipping.chapterTitle), sizeof(clipping.chapterTitle)) !=
            sizeof(clipping.chapterTitle)) {
      LOG_ERR("CLIP", "Failed to write clipping record %u: %s", i, storeFilePath.c_str());
      f.close();
      Storage.remove(tmpPath.c_str());
      return false;
    }

    const bool useReplacement = replacementText && i == replacementIndex;
    if (useReplacement) {
      fullText = *replacementText;
    } else if (!readClippingText(clipping, fullText)) {
      LOG_ERR("CLIP", "Failed to read clipping text %u for rewrite", i);
      f.close();
      Storage.remove(tmpPath.c_str());
      return false;
    }
    const uint16_t previewLength = static_cast<uint16_t>(std::min<size_t>(fullText.size(), DOWNGRADE_TEXT_MAX));
    if (!serialization::tryWritePod(f, previewLength)) {
      LOG_ERR("CLIP", "Failed to write clipping text length %u: %s", i, tmpPath.c_str());
      f.close();
      Storage.remove(tmpPath.c_str());
      return false;
    }

    const uint32_t previewOffset = static_cast<uint32_t>(f.position());
    if (previewLength > 0 &&
        f.write(reinterpret_cast<const uint8_t*>(fullText.data()), previewLength) != previewLength) {
      LOG_ERR("CLIP", "Failed to write clipping text %u: %s", i, tmpPath.c_str());
      f.close();
      Storage.remove(tmpPath.c_str());
      return false;
    }
    previewOffsets.push_back(previewOffset);
    previewLengths.push_back(previewLength);
  }

  if (!f.sync()) {
    LOG_ERR("CLIP", "Failed to sync clipping file: %s", tmpPath.c_str());
    f.close();
    Storage.remove(tmpPath.c_str());
    return false;
  }
  f.close();

  std::vector<uint32_t> sidecarTextOffsets;
  std::vector<uint16_t> sidecarTextLengths;
  if (!writeTagSidecarTemp(tmpPath, previewOffsets, previewLengths, replacementText, replacementIndex,
                           sidecarTextOffsets, sidecarTextLengths)) {
    Storage.remove(tmpPath.c_str());
    return false;
  }

  const bool hadCurrent = Storage.exists(storeFilePath.c_str());
  if (!AtomicFile::commit(storeFilePath, "CLIP")) {
    Storage.remove(AtomicFile::temporaryPath(sidecarPath).c_str());
    return false;
  }
  if (!AtomicFile::commit(sidecarPath, "CLIP")) {
    AtomicFile::rollback(storeFilePath, hadCurrent, "CLIP");
    return false;
  }
  for (uint16_t i = 0; i < count; ++i) {
    clippings[i].textOffset = sidecarTextOffsets[i];
    clippings[i].textLength = sidecarTextLengths[i];
    clippings[i].textInSidecar = true;
  }
  sourceFilePath = storeFilePath;
  sidecarSourceFilePath = sidecarPath;
  return true;
}

bool ClippingStore::hasAnyClippings() {
  if (!Storage.exists(CLIPPINGS_DIR)) return false;
  const auto files = Storage.listFiles(CLIPPINGS_DIR);
  for (const auto& name : files) {
    const std::string nameStr = name.c_str();
    if (nameStr.size() >= 4 && nameStr.compare(nameStr.size() - 4, 4, ".bin") == 0) return true;
  }
  return false;
}

bool ClippingStore::getAllClippedBooks(std::vector<ClippedBookEntry>& out) {
  if (!Storage.exists(CLIPPINGS_DIR)) return true;

  const auto files = Storage.listFiles(CLIPPINGS_DIR);
  for (const auto& name : files) {
    const std::string nameStr = name.c_str();
    if (nameStr.size() < 4 || nameStr.compare(nameStr.size() - 4, 4, ".bin") != 0) continue;
    ClippingFileHeader header;
    const std::string fullPath = std::string(CLIPPINGS_DIR) + "/" + name.c_str();
    if (!readClippingFileHeader(fullPath, name.c_str(), header)) continue;
    if (header.path.empty() || header.count == 0 || !Storage.exists(header.path.c_str())) continue;

    auto existing = std::find_if(out.begin(), out.end(), [&](const ClippedBookEntry& entry) {
      return entry.bookPath == header.path && entry.bookType == header.bookType;
    });
    if (existing != out.end()) {
      existing->count = std::max(existing->count, header.count);
      continue;
    }
    out.push_back({std::move(header.title), std::move(header.author), std::move(header.path),
                   std::move(header.bookType), header.count});
  }
  return true;
}

void ClippingStore::deleteForFilePath(const std::string& filePath, const std::string& bookType) {
  const std::string path = storeFilePathForBook(filePath, bookType);
  const std::array<std::string, 6> paths = {
      path,
      AtomicFile::temporaryPath(path),
      AtomicFile::backupPath(path),
      tagSidecarPath(path),
      AtomicFile::temporaryPath(tagSidecarPath(path)),
      AtomicFile::backupPath(tagSidecarPath(path)),
  };
  for (const std::string& candidate : paths) {
    if (Storage.exists(candidate.c_str())) Storage.remove(candidate.c_str());
  }
}

bool ClippingStore::migrateForFilePath(const std::string& oldFilePath, const std::string& newFilePath,
                                       const std::string& title, const std::string& author,
                                       const std::string& bookType) {
  return migrateForFilePath(oldFilePath, newFilePath, title, author, bookType,
                            KOReaderDocumentId::calculate(newFilePath));
}

bool ClippingStore::migrateForFilePath(const std::string& oldFilePath, const std::string& newFilePath,
                                       const std::string& title, const std::string& author,
                                       const std::string& bookType, const std::string& documentId) {
  const std::string oldStorePath = storeFilePathForBook(oldFilePath, bookType);
  const std::string oldBackupPath = AtomicFile::backupPath(oldStorePath);
  if (!Storage.exists(oldStorePath.c_str()) && !Storage.exists(oldBackupPath.c_str())) return true;
  const std::string oldSourcePath = Storage.exists(oldStorePath.c_str()) ? oldStorePath : oldBackupPath;

  ClippingStore reader;
  std::vector<Clipping> migratedClippings;
  reader.bookFilePath = oldFilePath;
  // The built-in move flow calls this after the EPUB itself has moved. Use
  // the destination content to authenticate the source annotation file.
  reader.bookDocumentId = documentId;
  if (!reader.readFromFile(oldSourcePath, migratedClippings)) {
    return false;
  }
  reader.storeFilePath = oldStorePath;
  reader.sourceFilePath = oldSourcePath;
  reader.clippings = std::move(migratedClippings);
  if (!reader.loadTagSidecar()) {
    LOG_ERR("CLIP", "Refusing to migrate clippings with an invalid tag sidecar");
    return false;
  }

  const std::string newStorePath = storeFilePathForBook(newFilePath, bookType);
  if (oldStorePath != newStorePath &&
      (Storage.exists(newStorePath.c_str()) || Storage.exists(AtomicFile::backupPath(newStorePath).c_str()) ||
       Storage.exists(tagSidecarPath(newStorePath).c_str()) ||
       Storage.exists(AtomicFile::backupPath(tagSidecarPath(newStorePath)).c_str()))) {
    LOG_ERR("CLIP", "Refusing to overwrite destination clipping store during migration: %s", newStorePath.c_str());
    return false;
  }

  ClippingStore writer;
  writer.bookFilePath = newFilePath;
  writer.bookTitle = title;
  writer.bookAuthor = author;
  writer.bookDocumentId = documentId;
  writer.storeFilePath = newStorePath;
  writer.sourceFilePath = oldSourcePath;
  writer.sidecarSourceFilePath = reader.sidecarSourceFilePath;
  writer.clippings = std::move(reader.clippings);
  writer.ready = true;
  if (!writer.writeToFile()) {
    return false;
  }

  if (oldStorePath == newStorePath) {
    return true;
  }

  const std::array<std::string, 6> oldPaths = {
      oldStorePath,
      AtomicFile::temporaryPath(oldStorePath),
      AtomicFile::backupPath(oldStorePath),
      tagSidecarPath(oldStorePath),
      AtomicFile::temporaryPath(tagSidecarPath(oldStorePath)),
      AtomicFile::backupPath(tagSidecarPath(oldStorePath)),
  };
  for (const std::string& candidate : oldPaths) {
    if (Storage.exists(candidate.c_str()) && !Storage.remove(candidate.c_str())) {
      LOG_ERR("CLIP", "Failed to remove migrated clipping source: %s", candidate.c_str());
      return false;
    }
  }
  return true;
}
