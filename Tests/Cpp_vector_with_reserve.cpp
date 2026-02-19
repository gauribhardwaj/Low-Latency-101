#include <vector>

int main() {
    std::vector<int> v;
    v.reserve(10000);
    for (int i = 0; i < 10000; i++) {
        v.push_back(i);
    }
    return 0;
}

