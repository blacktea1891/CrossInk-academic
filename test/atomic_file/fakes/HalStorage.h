#pragma once

#include <set>
#include <string>

class FakeStorage {
 public:
  std::set<std::string> files;
  std::string failRemovePath;
  std::string failRenameFrom;
  std::string failRenameTo;

  bool exists(const char* path) const { return files.count(path) != 0; }

  bool remove(const char* path) {
    if (failRemovePath == path) return false;
    return files.erase(path) != 0;
  }

  bool rename(const char* from, const char* to) {
    if (failRenameFrom == from && failRenameTo == to) return false;
    const auto source = files.find(from);
    if (source == files.end() || files.count(to) != 0) return false;
    files.erase(source);
    files.insert(to);
    return true;
  }

  void reset() {
    files.clear();
    failRemovePath.clear();
    failRenameFrom.clear();
    failRenameTo.clear();
  }
};

extern FakeStorage Storage;
