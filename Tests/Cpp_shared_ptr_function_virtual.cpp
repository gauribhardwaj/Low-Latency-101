#include <memory>
#include <functional>

struct Base { virtual void f() {} };
struct Der : Base { void f() override {} };

int main() {
    std::shared_ptr<Base> b = std::make_shared<Der>();
    std::function<void()> g = [&]() { b->f(); };
    for (int i = 0; i < 1000; i++) {
        g();
    }
    return 0;
}

