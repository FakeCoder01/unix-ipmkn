#include <filesystem>
#include <fstream>
#include <iostream>
#include <openssl/sha.h>
#include <string>
#include <unordered_map>
#include <vector>

namespace fs = std::filesystem;
using namespace std;

string calculateSHA1(const fs::path &path) {
  ifstream file(path, ios::binary);
  SHA_CTX shaContext;
  SHA1_Init(&shaContext);
  char buffer[8192];
  while (file.read(buffer, sizeof(buffer))) {
    SHA1_Update(&shaContext, buffer, file.gcount());
  }
  SHA1_Update(&shaContext, buffer, file.gcount());
  unsigned char hash[SHA_DIGEST_LENGTH];
  SHA1_Final(hash, &shaContext);

  char hex[SHA_DIGEST_LENGTH * 2 + 1];
  for (int i = 0; i < SHA_DIGEST_LENGTH; i++)
    sprintf(hex + (i * 2), "%02x", hash[i]);
  return string(hex);
}

void deduplicate(const fs::path &root) {
  // group files by size
  unordered_map<uintmax_t, vector<fs::path>> sizeMap;
  for (const auto &entry : fs::recursive_directory_iterator(root)) {
    if (fs::is_regular_file(entry)) {
      sizeMap[fs::file_size(entry)].push_back(entry.path());
    }
  }

  // hash only files with same sizes
  unordered_map<string, fs::path> hashMap;
  int linksCreated = 0;

  for (auto const &[size, paths] : sizeMap) {
    if (paths.size() < 2)
      continue; // skip unique sizes

    for (const auto &path : paths) {
      string hash = calculateSHA1(path);

      if (hashMap.find(hash) != hashMap.end()) {
        // potential duplicate found
        fs::path original = hashMap[hash];

        // don't link if they are already the same physical file
        if (fs::equivalent(original, path))
          continue;

        try {
          fs::remove(path);
          fs::create_hard_link(original, path);
          cout << "Linked: " << path.filename() << " -> " << original.filename()
               << endl;
          linksCreated++;
        } catch (fs::filesystem_error &e) {
          cerr << "Error linking " << path << ": " << e.what() << endl;
        }
      } else {
        hashMap[hash] = path;
      }
    }
  }
  cout << "\nFinished! Created " << linksCreated << " hard links." << endl;
}

int main(int argc, char *argv[]) {
  if (argc < 2) {
    cerr << "Usage: " << argv[0] << " <directory>" << endl;
    return 1;
  }
  deduplicate(argv[1]);
  return 0;
}
