#include <iostream>
#include <cstdlib>

int main() {
    for (int i = 0; i < 1000; i++) {
        int* p = (int*)std::malloc(64);
        std::cout << i;
    }
    return 0;
}

