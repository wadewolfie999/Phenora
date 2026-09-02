#include <Fastor/Fastor.h>
#include <cassert>
#include <complex>

// Regression coverage for Resummino's ARM64 scalar-complex compatibility patch.
int main() {
    using Complex = std::complex<double>;
    using Vector = Fastor::SIMDVector<Complex, Fastor::simd_abi::scalar>;
    Vector input(Complex(2.0, -3.0));
    auto result = -input;
    Complex value;
    result.store(&value, false);
    assert(value == Complex(-2.0, 3.0));

    Complex data[] = {Complex(1, 2), Complex(3, 4), Complex(5, 6)};
    Fastor::vector_setter(result, data, 1, 2);
    result.store(&value, false);
    assert(value == data[1]);

    Fastor::Tensor<Complex, 2, 4> tensor;
    Fastor::Tensor<Complex, 4> row = {Complex(1, 2), Complex(3, 4),
                                    Complex(5, 6), Complex(7, 8)};
    tensor(0, Fastor::all) = row;
    for (int i = 0; i < 4; ++i) {
        assert(tensor(0, i) == row(i));
    }
}
