// Driver for acme.com:user:adc_stream, hardware version 2.x.
//
// Register map (2.x):
//   0x00 CTRL    bit0 start, bit1 continuous
//   0x04 STATUS  bit0 busy, bit1 fifo_valid
//   0x08 FIFO    read-only sample word
//   0x0C COUNT   samples captured since start
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace acme {

class AdcStream {
public:
    explicit AdcStream(std::uintptr_t base_addr, std::string instance = "");

    void start(bool continuous = false);
    void stop();
    bool busy() const;
    std::uint32_t sample_count() const;

    // Pops up to `max_samples` words out of the capture FIFO.
    std::vector<std::uint32_t> read_samples(std::size_t max_samples);

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
