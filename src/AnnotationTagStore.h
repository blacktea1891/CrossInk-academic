#pragma once

#include <cstddef>
#include <cstdint>

// Tag definitions are deliberately kept outside CrossPointSettings. They are
// user data, not a firmware preference, and fixed records keep the C3 heap
// independent of the number of tags.
inline constexpr uint8_t ANNOTATION_TAG_MAX = 16;
inline constexpr size_t ANNOTATION_TAG_NAME_MAX = 32;

struct AnnotationTag {
  uint16_t id = 0;
  char name[ANNOTATION_TAG_NAME_MAX] = {};
};

class AnnotationTagStore {
 public:
  enum class LoadState : uint8_t {
    Unloaded,
    Ready,
    Failed,
  };

  static AnnotationTagStore& getInstance() { return instance; }

  bool load();
  bool save() const;

  uint8_t count() const { return tagCount; }
  const AnnotationTag* at(uint8_t index) const;
  const char* nameForId(uint16_t id) const;
  LoadState state() const { return loadState; }
  bool isReady() const { return loadState == LoadState::Ready; }

  bool add(const char* name);
  bool rename(uint8_t index, const char* name);
  bool remove(uint8_t index);

 private:
  static AnnotationTagStore instance;

  AnnotationTag tags[ANNOTATION_TAG_MAX]{};
  uint8_t tagCount = 0;
  uint16_t nextId = 1;
  LoadState loadState = LoadState::Unloaded;

  static constexpr const char* FILE_PATH = "/.crosspoint/annotation-tags.bin";
  static constexpr uint8_t FILE_VERSION = 1;

  bool readFromPath(const char* path);
  bool validName(const char* name) const;
};

#define ANNOTATION_TAGS AnnotationTagStore::getInstance()
