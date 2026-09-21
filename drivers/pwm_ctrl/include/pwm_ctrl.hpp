// Driver for acme.com:user:pwm_ctrl, hardware version 1.x.
//
// Register map (1.x):
//   0x00 CTRL    bit0 enable
//   0x04 DUTY0   duty for channel 0, in per-mille (0..1000)
//   0x08 DUTY1   duty for channel 1
//   0x0C IDREG   read-only magic + hardware version
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace acme {

class PwmCtrl {
public:
    static constexpr std::size_t kChannels = 2;

    explicit PwmCtrl(std::uintptr_t base_addr, std::string instance = "");

    void enable(bool on);
    bool enabled() const;

    // duty is per-mille: 0 = always low, 1000 = always high.
    void set_duty(std::size_t channel, std::uint16_t per_mille);
    std::uint16_t duty(std::size_t channel) const;

    const std::string& instance() const { return instance_; }
    std::uintptr_t base() const { return base_; }

    // Baked in at build time from the driver package and from the hardware
    // version ipman matched, so a binary can report what it was built against.
    static const char* driver_version();
    static const char* built_for_ip_version();

private:
    std::uint32_t read(std::size_t offset) const;
    void write(std::size_t offset, std::uint32_t value);

    std::uintptr_t base_;
    std::string instance_;
};

}  // namespace acme
