#include "mmio.hpp"

#ifdef IPDRV_SIMULATION
#include <array>
#include <map>

#include "pwm_ctrl_sim.hpp"
#endif

namespace acme {

#ifdef IPDRV_SIMULATION
namespace {

constexpr std::size_t kSimWords = 16;

std::array<std::uint32_t, kSimWords>& block(std::uintptr_t base) {
    static std::map<std::uintptr_t, std::array<std::uint32_t, kSimWords>> blocks;
    auto it = blocks.find(base);
    if (it == blocks.end()) {
        it = blocks.emplace(base, std::array<std::uint32_t, kSimWords>{}).first;
        // Out of reset the ID register reads as revision 1.0 until something
        // seeds a different one.
        it->second[0] = (0x5057u << 16) | (1u << 8) | 0u;
    }
    return it->second;
}

}  // namespace

namespace detail {

std::uint32_t read_word(std::uintptr_t base, std::size_t offset) {
    return block(base)[(offset / 4) % kSimWords];
}

void write_word(std::uintptr_t base, std::size_t offset, std::uint32_t value) {
    if (offset == 0) return;  // the ID register is read-only, even simulated
    block(base)[(offset / 4) % kSimWords] = value;
}

}  // namespace detail

void sim_set_ip_version(std::uintptr_t base, std::uint8_t major,
                        std::uint8_t minor) {
    block(base)[0] = (0x5057u << 16)
                   | (static_cast<std::uint32_t>(major) << 8)
                   | static_cast<std::uint32_t>(minor);
}

void sim_reset(std::uintptr_t base) {
    auto& regs = block(base);
    const std::uint32_t id = regs[0];
    regs.fill(0);
    regs[0] = id;
}

#else  // real hardware

namespace detail {

std::uint32_t read_word(std::uintptr_t base, std::size_t offset) {
    return *reinterpret_cast<volatile std::uint32_t*>(base + offset);
}

void write_word(std::uintptr_t base, std::size_t offset, std::uint32_t value) {
    *reinterpret_cast<volatile std::uint32_t*>(base + offset) = value;
}

}  // namespace detail

#endif

}  // namespace acme
