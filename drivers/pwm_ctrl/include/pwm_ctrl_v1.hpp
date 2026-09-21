// Register map for acme.com:user:pwm_ctrl, hardware revision 1.x.
//
// Generated from rdl/pwm_ctrl.rdl in a real flow:
//     peakrdl c-header rdl/pwm_ctrl.rdl -o generated/pwm_ctrl_v1.h --bitfields
// This file is hand-written and shaped like that output; the .rdl in this
// package is the register definition of record.
//
//   0x00  ID     ro   MAGIC[31:16]=0x5057  MAJOR[15:8]  MINOR[7:0]
//   0x04  CTRL   rw   ENABLE[0]
//   0x08  DUTY0  rw   DUTY[9:0]   per-mille, 0..1000
//   0x0C  DUTY1  rw   DUTY[9:0]
//
// The ID register is the cross-revision contract: same offset, same layout in
// every revision, so software can read it before it knows which revision it is
// talking to.
#pragma once

#include <cstddef>
#include <cstdint>

namespace acme {

class PwmCtrlV1 {
public:
    static constexpr std::size_t kChannels = 2;
    static constexpr std::size_t kIdOffset = 0x00;
    static constexpr std::uint32_t kMagic = 0x5057u;
    static constexpr std::uint16_t kMaxDuty = 1000;

    // Required by the generated ipman register-map union: it reads the ID
    // register through this before any instance exists, and this is the one
    // place that knows whether the build talks to MMIO or a simulation.
    static std::uint32_t read_word(std::uintptr_t base, std::size_t offset);

    explicit PwmCtrlV1(std::uintptr_t base);

    void enable(bool on);
    bool enabled() const;

    void set_duty(std::size_t channel, std::uint16_t per_mille);
    std::uint16_t duty(std::size_t channel) const;

    std::uintptr_t base() const { return base_; }
    std::uint8_t major() const;
    std::uint8_t minor() const;

private:
    std::uint32_t read(std::size_t offset) const;
    void write(std::size_t offset, std::uint32_t value);

    std::uintptr_t base_;
};

}  // namespace acme
