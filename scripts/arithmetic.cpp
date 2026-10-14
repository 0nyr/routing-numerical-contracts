#include <cstdint>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>

int main() {
    volatile double u = 1009, e = 250, l = 12360, s = 5;
    double old = (e+s) + ((u-e)/(l-e))*((l+s)-(e+s));
    double direct = (u > e ? u : e) + s;
    volatile double a = 1 + std::ldexp(1., -27), b = 1 - std::ldexp(1., -27);
    volatile double product = a * b;
    double split = product - 1;
    double fused = std::fma(a, b, -1.);
    std::cout << std::setprecision(17)
              << "{\"interpolation\":" << old << ",\"direct\":" << direct
              << ",\"split_product\":" << split << ",\"fused_product\":" << fused
              << ",\"binary64\":" << (std::numeric_limits<double>::is_iec559 && sizeof(double) == 8)
              << ",\"int64_max\":" << std::numeric_limits<std::int64_t>::max() << "}\n";
}
