#include "axi_gpio_lite.hpp"

#ifdef IPDRV_SIMULATION
#include <array>
#include <map>
#endif

namespace acme {
namespace {

constexpr std::size_t kData = 0x00;
constexpr std::size_t kTri = 0x04;

#ifdef IPDRV_SIMULATION
std::array<std::uint32_t, 8>& sim_block(std::uintptr_t base) {
    static std::map<std::uintptr_t, std::array<std::uint32_t, 8>> blocks;
    auto it = blocks.find(base);
    if (it == blocks.end()) {
        it = blocks.emplace(base, std::array<std::uint32_t, 8>{}).first;
        it->second[kTri / 4] = 0xFFFFFFFFu;  // all inputs out of reset
    }
    return it->second;
}
#endif

}  // namespace

AxiGpioLite::AxiGpioLite(std::uintptr_t base_addr, std::string instance)
    : base_(base_addr), instance_(std::move(instance)) {}

std::uint32_t AxiGpioLite::read(std::size_t offset) const {
#ifdef IPDRV_SIMULATION
    return sim_block(base_)[offset / 4];
#else
    return *reinterpret_cast<volatile std::uint32_t*>(base_ + offset);
#endif
}

void AxiGpioLite::write(std::size_t offset, std::uint32_t value) {
#ifdef IPDRV_SIMULATION
    sim_block(base_)[offset / 4] = value;
#else
    *reinterpret_cast<volatile std::uint32_t*>(base_ + offset) = value;
#endif
}

void AxiGpioLite::set_direction(std::uint32_t tri_mask) { write(kTri, tri_mask); }
std::uint32_t AxiGpioLite::direction() const { return read(kTri); }
void AxiGpioLite::write_pins(std::uint32_t value) { write(kData, value); }
std::uint32_t AxiGpioLite::read_pins() const { return read(kData); }

const char* AxiGpioLite::driver_version() {
#ifdef GPIO_LITE_DRIVER_VERSION
    return GPIO_LITE_DRIVER_VERSION;
#else
    return "unknown";
#endif
}

}  // namespace acme
