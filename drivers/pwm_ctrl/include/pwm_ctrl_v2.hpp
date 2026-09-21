// Register map for acme.com:user:pwm_ctrl, hardware revision 2.x.
//
// What changed from 1.x, and why it is a major bump: DUTY widened from 10 to
// 16 bits, CTRL gained INVERT, and two PHASE registers were added. Existing
// offsets kept their meaning, but the duty field resized, so 1.x software
// writing a 2.x block would program the wrong value.
//
//   0x00  ID      ro   MAGIC[31:16]=0x5057  MAJOR[15:8]  MINOR[7:0]
//   0x04  CTRL    rw   ENABLE[0]  INVERT[1]
//   0x08  DUTY0   rw   DUTY[15:0]   per-mille, 0..1000
//   0x0C  DUTY1   rw   DUTY[15:0]
//   0x10  PHASE0  rw   PHASE[15:0]  new in 2.x
//   0x14  PHASE1  rw   PHASE[15:0]
#pragma once

#include <cstddef>
#include <cstdint>

namespace acme {

class PwmCtrlV2 {
public:
    static constexpr std::size_t kChannels = 2;
    static constexpr std::size_t kIdOffset = 0x00;
    static constexpr std::uint32_t kMagic = 0x5057u;
    static constexpr std::uint16_t kMaxDuty = 1000;

    static std::uint32_t read_word(std::uintptr_t base, std::size_t offset);

    explicit PwmCtrlV2(std::uintptr_t base);

    // The part of the interface 1.x also has, so std::visit can drive either.
    void enable(bool on);
    bool enabled() const;
    void set_duty(std::size_t channel, std::uint16_t per_mille);
    std::uint16_t duty(std::size_t channel) const;
    std::uintptr_t base() const { return base_; }
    std::uint8_t major() const;
    std::uint8_t minor() const;

    // 2.x only. Reaching these means asking the variant for this alternative
    // specifically, which is the point: the compiler stops you using them on a
    // 1.x block.
    void set_invert(bool on);
    bool inverted() const;
    void set_phase(std::size_t channel, std::uint16_t per_mille);
    std::uint16_t phase(std::size_t channel) const;

private:
    std::uint32_t read(std::size_t offset) const;
    void write(std::size_t offset, std::uint32_t value);

    std::uintptr_t base_;
};

}  // namespace acme
