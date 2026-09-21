// hello_fpga -- a hello world that knows what is in its bitstream.
//
// Nothing here is hand-maintained. ipman_ips.h is generated from the XSA at
// configure time; ipman_maps.hpp is generated from the manifests of whichever
// driver packages were resolved, and gives each IP a std::variant over every
// register-map revision those drivers can serve.
//
// Two different questions, answered in two different places:
//   build time -- which driver sources does this bitstream need?  (the lock)
//   run time   -- which register layout is actually out there?    (the probe)

#include <cstdio>
#include <variant>

#include "ipman_ips.h"
#include "ipman_maps.hpp"

#ifdef IPMAN_HAS_PWM_CTRL
#include "pwm_ctrl_sim.hpp"
#endif

#if __has_include("adc_stream.hpp")
#include "adc_stream.hpp"
#define HAVE_ADC_STREAM 1
#endif

#if __has_include("axi_gpio_lite.hpp")
#include "axi_gpio_lite.hpp"
#define HAVE_AXI_GPIO_LITE 1
#endif

namespace {

void print_inventory() {
    std::printf("hello_fpga\n");
    std::printf("  hardware      : %s\n", IPMAN_XSA_FILE);
    std::printf("  driver db     : v%s\n", IPMAN_DB_VERSION);
    std::printf("  custom IP     : %d\n\n", IPMAN_IP_COUNT);

    std::printf("  %-18s %-34s %-12s %s\n", "INSTANCE", "VLNV", "BASE", "DRIVER");
    for (int i = 0; i < IPMAN_IP_COUNT; ++i) {
        const ipman_ip_info_t& ip = IPMAN_IPS[i];
        std::printf("  %-18s %-34s 0x%08lX   %s\n", ip.instance, ip.vlnv,
                    ip.base_addr, ip.driver[0] ? ip.driver : "(no driver)");
    }
    std::printf("\n");
}

#ifdef IPMAN_HAS_PWM_CTRL
// Binds one pwm_ctrl block by asking the hardware what it is, then drives it
// through whichever register map came back.
void drive_pwm(std::uintptr_t base, const char* instance) {
    const ipman::Probe p = ipman::pwm_ctrl::probe(base);
    if (!p.valid) {
        std::printf("  %-14s @0x%08lX  no pwm_ctrl here (ID reads 0x%08X)\n",
                    instance, static_cast<unsigned long>(base), p.raw);
        return;
    }

    auto map = ipman::pwm_ctrl::bind(base);
    if (!map) {
        std::printf("  %-14s @0x%08lX  hardware is %u.%u, no linked driver "
                    "serves that revision\n", instance,
                    static_cast<unsigned long>(base), p.version.major,
                    p.version.minor);
        return;
    }

    std::printf("  %-14s @0x%08lX  hardware %u.%u -> %s%s\n", instance,
                static_cast<unsigned long>(base), p.version.major,
                p.version.minor, ipman::pwm_ctrl::map_name(*map),
                ipman::pwm_ctrl::matches_build(base) ? "" : "  [differs from build]");

    // The part every revision shares: one call site, either layout.
    std::visit([](auto& pwm) {
        pwm.enable(true);
        pwm.set_duty(0, 250);
        pwm.set_duty(1, 750);
    }, *map);

    std::visit([](auto& pwm) {
        std::printf("                   enabled=%d duty=[%u, %u]\n",
                    static_cast<int>(pwm.enabled()), pwm.duty(0), pwm.duty(1));
    }, *map);

    // The part only 2.x has. Asking for the alternative by type is what makes
    // this safe: on a 1.x block the pointer is null, and there is no way to
    // call set_phase on a layout that has no phase register.
    if (auto* v2 = std::get_if<acme::PwmCtrlV2>(&*map)) {
        v2->set_invert(true);
        v2->set_phase(0, 125);
        std::printf("                   2.x extras: invert=%d phase0=%u\n",
                    static_cast<int>(v2->inverted()), v2->phase(0));
    }
}
#endif

}  // namespace

int main() {
    print_inventory();

#ifdef IPMAN_HAS_PWM_CTRL
    std::printf("pwm_ctrl: built for IP %s, driver serves %s\n",
                ipman::pwm_ctrl::kBuiltFor, "1.* and 2.*");

    // Simulation only: make the second block report itself as a 2.0 revision,
    // as a newer bitstream would. Nothing is rebuilt -- the same binary binds
    // a different register map.
    acme::sim_set_ip_version(PWM_CTRL_0_BASEADDR, 1, 2);
    acme::sim_set_ip_version(PWM_CTRL_1_BASEADDR, 2, 0);

    drive_pwm(PWM_CTRL_0_BASEADDR, "pwm_ctrl_0");
    drive_pwm(PWM_CTRL_1_BASEADDR, "pwm_ctrl_1");
    std::printf("\n");
#endif

#ifdef HAVE_ADC_STREAM
    std::printf("adc_stream driver %s\n", acme::AdcStream::driver_version());
    acme::AdcStream adc(ADC_STREAM_0_BASEADDR, "adc_stream_0");
    adc.start(/*continuous=*/true);
    const auto samples = adc.read_samples(4);
    std::printf("  %-14s @0x%08lX captured %u sample(s):",
                adc.instance().c_str(), static_cast<unsigned long>(adc.base()),
                adc.sample_count());
    for (std::uint32_t sample : samples) std::printf(" 0x%04X", sample);
    adc.stop();
    std::printf("\n\n");
#endif

#ifdef HAVE_AXI_GPIO_LITE
    std::printf("axi_gpio_lite driver %s\n", acme::AxiGpioLite::driver_version());
    acme::AxiGpioLite gpio(AXI_GPIO_LITE_0_BASEADDR, "axi_gpio_lite_0");
    gpio.set_direction(0xFFFF0000u);  // low half outputs
    gpio.write_pins(0x0000A5A5u);
    std::printf("  %-14s @0x%08lX tri=0x%08X pins=0x%08X\n\n",
                gpio.instance().c_str(), static_cast<unsigned long>(gpio.base()),
                gpio.direction(), gpio.read_pins());
#endif

    std::printf("all drivers exercised.\n");
    return 0;
}
