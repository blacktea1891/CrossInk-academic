#include "PageTagStore.h"

#include <HalStorage.h>
#include <Logging.h>
#include <Serialization.h>
#include <uzlib.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <utility>

#include "AnnotationTagStore.h"
#include "PageTagProgress.h"
#include "util/AtomicFile.h"

namespace {
constexpr uint8_t LEGACY_FILE_VERSION = 1;
constexpr uint8_t FILE_VERSION = 2;
constexpr uint16_t MAX_PAGE_TAGS = 256;
constexpr char PAGE_TAGS_DIR[] = "/.crosspoint/page-tags";

}  // namespace

PageTagStore PageTagStore::instance;

std::string PageTagStore::storeFilePathForBook(const std::string& filePath, const std::string& bookType) {
  const uint32_t crc = uzlib_crc32(filePath.data(), static_cast<unsigned int>(filePath.size()), 0);
  return std::string(PAGE_TAGS_DIR) + "/" + bookType + "_" + std::to_string(crc) + ".bin";
}

bool PageTagStore::loadForBook(const std::string& filePath, const std::string& documentId,
                               const std::string& bookType) {
  if (bookType != "epub") {
    LOG_ERR("TAGS", "Unknown page tag book type: %s", bookType.c_str());
    return false;
  }

  bookFilePath = filePath;
  bookDocumentId = documentId;
  storeFilePath = storeFilePathForBook(filePath, bookType);
  pageTags.clear();
  pageTags.reserve(8);
  dirty = false;
  ready = false;
  loadedLegacyVersion = false;

  const std::string backupPath = AtomicFile::backupPath(storeFilePath);
  const bool hasCurrent = Storage.exists(storeFilePath.c_str());
  const bool hasBackup = Storage.exists(backupPath.c_str());
  if (!hasCurrent && !hasBackup) {
    ready = true;
    return true;
  }
  if (hasCurrent && readFromFile(storeFilePath)) {
    ready = true;
    if (loadedLegacyVersion && !writeToFile()) LOG_ERR("TAGS", "Failed to migrate legacy page tags");
    return true;
  }
  if (hasBackup && readFromFile(backupPath)) {
    if (hasCurrent && !Storage.remove(storeFilePath.c_str())) {
      LOG_ERR("TAGS", "Recovered page tags but could not remove corrupt current file: %s", storeFilePath.c_str());
      pageTags.clear();
      return false;
    }
    LOG_INF("TAGS", "Loaded page tags from backup: %s", backupPath.c_str());
    ready = true;
    if (loadedLegacyVersion && !writeToFile()) LOG_ERR("TAGS", "Failed to migrate recovered legacy page tags");
    return true;
  }
  pageTags.clear();
  return false;
}

void PageTagStore::unload() {
  if (dirty && ready) writeToFile();
  pageTags.clear();
  bookFilePath.clear();
  bookDocumentId.clear();
  storeFilePath.clear();
  dirty = false;
  ready = false;
  loadedLegacyVersion = false;
}

uint16_t PageTagStore::tagForPage(const uint16_t spineIndex, const float pageProgress,
                                  const uint16_t pageCount) const {
  const auto it = std::find_if(pageTags.begin(), pageTags.end(), [&](const PageTag& entry) {
    return entry.spineIndex == spineIndex && page_tags::progressFallsOnPage(entry.progress, pageProgress, pageCount);
  });
  if (it == pageTags.end()) return 0;
  if (ANNOTATION_TAGS.isReady() && !ANNOTATION_TAGS.nameForId(it->tagId)) return 0;
  return it->tagId;
}

bool PageTagStore::setTagForPage(const uint16_t spineIndex, const float pageProgress, const uint16_t pageCount,
                                 const uint16_t tagId) {
  if (!ready) {
    LOG_ERR("TAGS", "Refusing to change page tags before a successful load");
    return false;
  }
  auto it = std::find_if(pageTags.begin(), pageTags.end(), [&](const PageTag& entry) {
    return entry.spineIndex == spineIndex && page_tags::progressFallsOnPage(entry.progress, pageProgress, pageCount);
  });

  if (tagId == 0) {
    if (it == pageTags.end()) return true;
    const size_t index = static_cast<size_t>(it - pageTags.begin());
    const PageTag removed = *it;
    pageTags.erase(it);
    dirty = true;
    if (writeToFile()) {
      dirty = false;
      return true;
    }
    pageTags.insert(pageTags.begin() + index, removed);
  } else if (it != pageTags.end()) {
    const PageTag previous = *it;
    it->progress = page_tags::midpointProgress(pageProgress, pageCount);
    it->tagId = tagId;
    dirty = true;
    if (writeToFile()) {
      dirty = false;
      return true;
    }
    *it = previous;
  } else {
    if (pageTags.size() >= MAX_PAGE_TAGS) {
      LOG_ERR("TAGS", "Page tag limit (%u) reached", MAX_PAGE_TAGS);
      return false;
    }
    pageTags.push_back(PageTag{spineIndex, page_tags::midpointProgress(pageProgress, pageCount), tagId});
    dirty = true;
    if (writeToFile()) {
      dirty = false;
      return true;
    }
    pageTags.pop_back();
  }

  dirty = true;
  return false;
}

bool PageTagStore::clearUnknownTagIds() {
  if (!ready || !ANNOTATION_TAGS.isReady()) return false;
  const size_t previousSize = pageTags.size();
  pageTags.erase(std::remove_if(pageTags.begin(), pageTags.end(), [](const PageTag& entry) {
                   return entry.tagId != 0 && !ANNOTATION_TAGS.nameForId(entry.tagId);
                 }),
                 pageTags.end());
  if (pageTags.size() == previousSize) return true;
  dirty = true;
  if (writeToFile()) {
    dirty = false;
    return true;
  }
  return false;
}

bool PageTagStore::readFromFile(const std::string& pathToRead) {
  FsFile file;
  if (!Storage.openFileForRead("TAGS", pathToRead, file)) return false;

  uint8_t version = 0;
  uint16_t count = 0;
  std::string title;
  std::string author;
  std::string path;
  std::string documentId;
  if (!serialization::tryReadPod(file, version) ||
      (version != LEGACY_FILE_VERSION && version != FILE_VERSION) || !serialization::tryReadPod(file, count) ||
      count > MAX_PAGE_TAGS) {
    file.close();
    LOG_ERR("TAGS", "Invalid page tag store: %s", pathToRead.c_str());
    return false;
  }

  if (version == LEGACY_FILE_VERSION &&
      (!serialization::tryReadString(file, title) || !serialization::tryReadString(file, author))) {
    file.close();
    LOG_ERR("TAGS", "Invalid legacy page tag metadata: %s", pathToRead.c_str());
    return false;
  }
  if (!serialization::tryReadString(file, path) || !serialization::tryReadString(file, documentId)) {
    file.close();
    LOG_ERR("TAGS", "Invalid page tag identity: %s", pathToRead.c_str());
    return false;
  }

  if (path != bookFilePath || (!documentId.empty() && documentId != bookDocumentId)) {
    file.close();
    LOG_ERR("TAGS", "Ignoring page tags belonging to another document: %s", pathToRead.c_str());
    return false;
  }

  std::vector<PageTag> loaded;
  loaded.reserve(count);
  for (uint16_t i = 0; i < count; ++i) {
    PageTag entry;
    if (!serialization::tryReadPod(file, entry.spineIndex)) {
      file.close();
      LOG_ERR("TAGS", "Truncated page tag store at record %u", i);
      return false;
    }
    if (version == LEGACY_FILE_VERSION) {
      uint16_t page = 0;
      uint16_t pageCount = 1;
      if (!serialization::tryReadPod(file, page) || !serialization::tryReadPod(file, pageCount) ||
          !serialization::tryReadPod(file, entry.tagId)) {
        file.close();
        LOG_ERR("TAGS", "Truncated legacy page tag store at record %u", i);
        return false;
      }
      const uint16_t safePageCount = std::max<uint16_t>(1, pageCount);
      const float pageProgress = static_cast<float>(std::min<uint16_t>(page, safePageCount - 1)) /
                                 static_cast<float>(safePageCount);
      entry.progress = page_tags::midpointProgress(pageProgress, safePageCount);
    } else if (!serialization::tryReadPod(file, entry.progress) || !serialization::tryReadPod(file, entry.tagId)) {
      file.close();
      LOG_ERR("TAGS", "Truncated page tag store at record %u", i);
      return false;
    }
    if (entry.tagId != 0 && std::isfinite(entry.progress) && entry.progress >= 0.0f && entry.progress <= 1.0f) {
      loaded.push_back(entry);
    }
  }
  file.close();
  pageTags = std::move(loaded);
  loadedLegacyVersion = version == LEGACY_FILE_VERSION;
  return true;
}

bool PageTagStore::writeToFile() const {
  if (!ready) {
    LOG_ERR("TAGS", "Refusing to save page tags before a successful load");
    return false;
  }
  Storage.mkdir("/.crosspoint");
  Storage.mkdir(PAGE_TAGS_DIR);

  const std::string tmpPath = AtomicFile::temporaryPath(storeFilePath);
  if (!AtomicFile::prepare(storeFilePath, "TAGS")) return false;

  FsFile file;
  if (!Storage.openFileForWrite("TAGS", tmpPath, file)) {
    LOG_ERR("TAGS", "Failed to open page tag store for write: %s", storeFilePath.c_str());
    return false;
  }

  const uint16_t count = static_cast<uint16_t>(std::min<size_t>(pageTags.size(), MAX_PAGE_TAGS));
  bool ok = serialization::tryWritePod(file, FILE_VERSION) && serialization::tryWritePod(file, count) &&
            serialization::tryWriteString(file, bookFilePath) && serialization::tryWriteString(file, bookDocumentId);
  for (uint16_t i = 0; ok && i < count; ++i) {
    const PageTag& entry = pageTags[i];
    ok = serialization::tryWritePod(file, entry.spineIndex) && serialization::tryWritePod(file, entry.progress) &&
         serialization::tryWritePod(file, entry.tagId);
  }
  ok = ok && file.sync();
  file.close();
  if (!ok) {
    Storage.remove(tmpPath.c_str());
    LOG_ERR("TAGS", "Failed to write page tag store: %s", storeFilePath.c_str());
    return false;
  }

  return AtomicFile::commit(storeFilePath, "TAGS");
}

void PageTagStore::deleteForFilePath(const std::string& filePath, const std::string& bookType) {
  const std::string path = storeFilePathForBook(filePath, bookType);
  if (Storage.exists(path.c_str())) Storage.remove(path.c_str());
  const std::string tmpPath = path + ".tmp";
  const std::string backupPath = path + ".bak";
  if (Storage.exists(tmpPath.c_str())) Storage.remove(tmpPath.c_str());
  if (Storage.exists(backupPath.c_str())) Storage.remove(backupPath.c_str());
}

bool PageTagStore::migrateForFilePath(const std::string& oldFilePath, const std::string& newFilePath,
                                      const std::string& documentId, const std::string& bookType) {
  if (bookType != "epub" || oldFilePath.empty() || newFilePath.empty() || oldFilePath == newFilePath) return true;

  const std::string oldStorePath = storeFilePathForBook(oldFilePath, bookType);
  const std::string oldBackupPath = AtomicFile::backupPath(oldStorePath);
  if (!Storage.exists(oldStorePath.c_str()) && !Storage.exists(oldBackupPath.c_str())) return true;

  PageTagStore reader;
  reader.bookFilePath = oldFilePath;
  reader.bookDocumentId = documentId;
  reader.storeFilePath = oldStorePath;
  if (!reader.readFromFile(Storage.exists(oldStorePath.c_str()) ? oldStorePath : oldBackupPath)) return false;

  PageTagStore writer;
  writer.bookFilePath = newFilePath;
  writer.bookDocumentId = documentId;
  writer.storeFilePath = storeFilePathForBook(newFilePath, bookType);
  if (oldStorePath != writer.storeFilePath &&
      (Storage.exists(writer.storeFilePath.c_str()) ||
       Storage.exists(AtomicFile::backupPath(writer.storeFilePath).c_str()))) {
    LOG_ERR("TAGS", "Refusing to overwrite destination page tags during migration: %s",
            writer.storeFilePath.c_str());
    return false;
  }
  writer.pageTags = std::move(reader.pageTags);
  writer.ready = true;
  if (!writer.writeToFile()) return false;

  if (oldStorePath != writer.storeFilePath) {
    const std::array<std::string, 3> oldPaths = {
        oldStorePath,
        AtomicFile::temporaryPath(oldStorePath),
        AtomicFile::backupPath(oldStorePath),
    };
    for (const std::string& candidate : oldPaths) {
      if (Storage.exists(candidate.c_str()) && !Storage.remove(candidate.c_str())) {
        LOG_ERR("TAGS", "Failed to remove migrated page tag source: %s", candidate.c_str());
        return false;
      }
    }
  }
  return true;
}
