#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct PageTag {
  uint16_t spineIndex = 0;
  float progress = 0.0f;
  uint16_t tagId = 0;
};

class PageTagStore {
 public:
  static PageTagStore& getInstance() { return instance; }

  bool loadForBook(const std::string& filePath, const std::string& documentId, const std::string& bookType);
  void unload();

  uint16_t tagForPage(uint16_t spineIndex, float pageProgress, uint16_t pageCount) const;
  bool setTagForPage(uint16_t spineIndex, float pageProgress, uint16_t pageCount, uint16_t tagId);
  bool clearUnknownTagIds();
  bool hasTagForPage(uint16_t spineIndex, float pageProgress, uint16_t pageCount) const {
    return tagForPage(spineIndex, pageProgress, pageCount) != 0;
  }

  static void deleteForFilePath(const std::string& filePath, const std::string& bookType);
  static bool migrateForFilePath(const std::string& oldFilePath, const std::string& newFilePath,
                                 const std::string& documentId, const std::string& bookType);

 private:
  static PageTagStore instance;

  std::vector<PageTag> pageTags;
  std::string bookFilePath;
  std::string bookDocumentId;
  std::string storeFilePath;
  bool dirty = false;
  bool ready = false;
  bool loadedLegacyVersion = false;

  bool readFromFile(const std::string& path);
  bool writeToFile() const;
  static std::string storeFilePathForBook(const std::string& filePath, const std::string& bookType);
};

#define PAGE_TAGS PageTagStore::getInstance()
