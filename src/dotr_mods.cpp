#include "dotr_mods.h"
#include "ps2_runtime.h"
#include <cstring>
#include <iostream>

namespace
{
    // Map HUD: sub_002347D0 draws the player's panel and copies the deck's DC (sub_00215F00(0, slot)) to 0x1ED5442;
    // sub_002354A0 draws the opponent's panel and copies sub_00215F00(1, 0) to 0x1ED5444. Their only reader is the
    // map's duel check in sub_00237730 (0x239E34: `if (mine > opponent) refuse`). The panels show their own copies of
    // the values, so raising 0x1ED5444 after the opponent's panel changes the check only.
    constexpr uint32_t kOpponentPanel = 0x2354A0u, kOpponentDcCopy = 0x1ED5444u;
    Ps2RecompiledFunction g_opponentPanel = nullptr;

    void opponentPanelNoDcLimit(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_opponentPanel(rdram, ctx, runtime);
        const int16_t max = 0x7FFF;
        std::memcpy(rdram + kOpponentDcCopy, &max, sizeof(max));
    }
}

void dotrInstallNoDeckCostLimit(PS2Runtime &runtime)
{
    g_opponentPanel = runtime.lookupFunction(kOpponentPanel);
    if (!g_opponentPanel || !runtime.registerFunction(kOpponentPanel, opponentPanelNoDcLimit))
    {
        std::cerr << "[mod] no deck cost limit: sub_002354A0 not found, mod off" << std::endl;
        return;
    }
    std::cerr << "[mod] no deck cost limit: on" << std::endl;
}
