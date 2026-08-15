#include "AnnotationTagStore.h"

#include <HalStorage.h>
#include <Logging.h>
#include <Serialization.h>

#include <cstring>
#include <string>

#include "util/AtomicFile.h"

AnnotationTagStore AnnotationTagStore::instance;

const AnnotationTag* AnnotationTagStore::at(const uint8_t index) const {
  return index < tagCount ? &tags[index] : nullptr;
}

const char* AnnotationTagStore::nameForId(const uint16_t id) const {
  if (id == 0) return nullptr;
  for (uint8_t i = 0; i < tagCount; ++i) {
    if (tags[i].id == id) return tags[i].name;
  }
  return nullptr;
}

bool AnnotationTagStore::validName(const char* name) const {
  if (!name || name[0] == '\0' || strlen(name) >= ANNOTATION_TAG_NAME_MAX) return false;
  for (uint8_t i = 0; i < tagCount; ++i) {
    if (strcmp(tags[i].name, name) == 0) return false;
  }
  return true;
}

bool AnnotationTagStore::load() {
  if (loadState == LoadState::Ready) return true;

  loadState = LoadState::Unloaded;
  tagCount = 0;
  nextId = 1;

  const std::string backupPath = AtomicFile::backupPath(FILE_PATH);
  const bool hasCurrent = Storage.exists(FILE_PATH);
  const bool hasBackup = Storage.exists(backupPath.c_str());
  if (!hasCurrent && !hasBackup) {
    loadState = LoadState::Ready;
    return true;
  }

  if (hasCurrent && readFromPath(FILE_PATH)) {
    loadState = LoadState::Ready;
    return true;
  }

  if (hasBackup && readFromPath(backupPath.c_str())) {
    if (hasCurrent && !Storage.remove(FILE_PATH)) {
      LOG_ERR("TAGS", "Recovered backup but could not remove corrupt tag store");
      loadState = LoadState::Failed;
      return false;
    }
    LOG_INF("TAGS", "Loaded annotation tags from backup");
    loadState = LoadState::Ready;
    return true;
  }

  tagCount = 0;
  nextId = 1;
  loadState = LoadState::Failed;
  return false;
}

bool AnnotationTagStore::readFromPath(const char* path) {
  tagCount = 0;
  nextId = 1;

  FsFile file;
  if (!Storage.openFileForRead("TAGS", path, file)) {
    LOG_ERR("TAGS", "Failed to open tag store: %s", path);
    return false;
  }

  uint8_t version = 0;
  uint8_t storedCount = 0;
  if (!serialization::tryReadPod(file, version) || version != FILE_VERSION ||
      !serialization::tryReadPod(file, storedCount) || storedCount > ANNOTATION_TAG_MAX ||
      !serialization::tryReadPod(file, nextId)) {
    file.close();
    LOG_ERR("TAGS", "Invalid tag store header: %s", path);
    tagCount = 0;
    nextId = 1;
    return false;
  }

  for (uint8_t i = 0; i < storedCount; ++i) {
    AnnotationTag tag;
    if (!serialization::tryReadPod(file, tag.id) ||
        file.read(reinterpret_cast<uint8_t*>(tag.name), sizeof(tag.name)) != static_cast<int>(sizeof(tag.name))) {
      file.close();
      tagCount = 0;
      nextId = 1;
      LOG_ERR("TAGS", "Truncated tag store at record %u: %s", i, path);
      return false;
    }
    tag.name[sizeof(tag.name) - 1] = '\0';
    if (tag.id == 0 || tag.name[0] == '\0') continue;
    tags[tagCount++] = tag;
  }
  file.close();

  if (nextId == 0) nextId = 1;
  return true;
}

bool AnnotationTagStore::save() const {
  if (loadState != LoadState::Ready) {
    LOG_ERR("TAGS", "Refusing to save annotation tags before a successful load");
    return false;
  }
  Storage.mkdir("/.crosspoint");

  const std::string targetPath = FILE_PATH;
  const std::string tmpPath = AtomicFile::temporaryPath(targetPath);
  if (!AtomicFile::prepare(targetPath, "TAGS")) return false;

  FsFile file;
  if (!Storage.openFileForWrite("TAGS", tmpPath, file)) {
    LOG_ERR("TAGS", "Failed to open tag store for write");
    return false;
  }

  bool ok = serialization::tryWritePod(file, FILE_VERSION) && serialization::tryWritePod(file, tagCount) &&
            serialization::tryWritePod(file, nextId);
  for (uint8_t i = 0; ok && i < tagCount; ++i) {
    ok = serialization::tryWritePod(file, tags[i].id) &&
         file.write(reinterpret_cast<const uint8_t*>(tags[i].name), sizeof(tags[i].name)) ==
             static_cast<int>(sizeof(tags[i].name));
  }
  ok = ok && file.sync();
  file.close();
  if (!ok) {
    Storage.remove(tmpPath.c_str());
    LOG_ERR("TAGS", "Failed to write tag store");
    return false;
  }

  return AtomicFile::commit(targetPath, "TAGS");
}

bool AnnotationTagStore::add(const char* name) {
  if (!load()) return false;
  if (tagCount >= ANNOTATION_TAG_MAX || !validName(name)) return false;

  const uint16_t previousNextId = nextId;
  AnnotationTag& tag = tags[tagCount++];
  tag.id = nextId++;
  if (tag.id == 0) tag.id = nextId++;
  strncpy(tag.name, name, sizeof(tag.name) - 1);
  tag.name[sizeof(tag.name) - 1] = '\0';
  if (save()) return true;

  --tagCount;
  nextId = previousNextId;
  return false;
}

bool AnnotationTagStore::rename(const uint8_t index, const char* name) {
  if (!load()) return false;
  if (index >= tagCount || !name || name[0] == '\0' || strlen(name) >= ANNOTATION_TAG_NAME_MAX) return false;
  for (uint8_t i = 0; i < tagCount; ++i) {
    if (i != index && strcmp(tags[i].name, name) == 0) return false;
  }

  char oldName[ANNOTATION_TAG_NAME_MAX];
  strncpy(oldName, tags[index].name, sizeof(oldName));
  strncpy(tags[index].name, name, sizeof(tags[index].name) - 1);
  tags[index].name[sizeof(tags[index].name) - 1] = '\0';
  if (save()) return true;

  strncpy(tags[index].name, oldName, sizeof(tags[index].name));
  tags[index].name[sizeof(tags[index].name) - 1] = '\0';
  return false;
}

bool AnnotationTagStore::remove(const uint8_t index) {
  if (!load()) return false;
  if (index >= tagCount) return false;

  const AnnotationTag removed = tags[index];
  for (uint8_t i = index + 1; i < tagCount; ++i) tags[i - 1] = tags[i];
  --tagCount;
  if (save()) return true;

  for (uint8_t i = tagCount; i > index; --i) tags[i] = tags[i - 1];
  tags[index] = removed;
  ++tagCount;
  return false;
}
