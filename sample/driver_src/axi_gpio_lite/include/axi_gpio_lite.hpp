// Driver for acme.com:user:axi_gpio_lite, hardware version 1.x.
//
// Register map (1.x):
//   0x00 DATA  read: pin state, write: output value
//   0x04 TRI   1 = input, 0 = output
#pragma once

#include <cstdint>
#include <string>

namespace acme {

class AxiGpioLite {
public:
    explicit AxiGpioLite(std::uintptr_t base_addr, std::string instance = "");

    void set_direction(std::uint32_t tri_mask);
    std::uint32_t direction() const;

    void write_pins(std::uint32_t value);
    std::uint32_t read_pins() const;

    const std::string& instance() const { return instance_; }
    std::uintptr_t base() const { return base_; }
    static const char* driver_version();

private:
    std::uint32_t read(std::size_t offset) const;
    void write(std::size_t offset, std::uint32_t value);

    std::uintptr_t base_;
    std::string instance_;
};

}  // namespace acme
