// Picks the recompiled overlay by the module header that sub_001F4900 copies to 0x1E00000 ("MWo3", id at +4).
#include "dotr_overlays.h"
#include "ps2_overlay_resolver.h"
#include <algorithm>
#include <cstdio>
#include <cstring>

namespace
{
    constexpr uint32_t kDotrOverlayBase = 0x1E00000u, kDotrOverlayEnd = 0x1E08000u, kDotrOverlayMagic = 0x336F574Du;
    constexpr uint32_t kDotrOverlayMaxId = 0x400u;

    struct DotrOverlayTable
    {
        const DotrOverlayEntry *entries;
        size_t count;
    };

    DotrOverlayTable *dotrOverlayTables()
    {
        static DotrOverlayTable tables[kDotrOverlayMaxId] = {};
        return tables;
    }

    PS2Runtime::RecompiledFunction resolveDotrOverlay(const uint8_t *rdram, uint32_t address)
    {
        if (!rdram || address < kDotrOverlayBase || address >= kDotrOverlayEnd)
        {
            return nullptr;
        }
        uint32_t magic = 0u, id = 0u;
        std::memcpy(&magic, rdram + kDotrOverlayBase, 4);
        std::memcpy(&id, rdram + kDotrOverlayBase + 4, 4);
        if (magic != kDotrOverlayMagic || id >= kDotrOverlayMaxId)
        {
            return nullptr;
        }
        const DotrOverlayTable &table = dotrOverlayTables()[id];
        const DotrOverlayEntry *end = table.entries + table.count;
        const DotrOverlayEntry *it = std::lower_bound(table.entries, end, address,
                                                      [](const DotrOverlayEntry &e, uint32_t a) { return e.address < a; });
        if (it == end || it->address != address)
        {
            std::fprintf(stderr, "[dotr-overlay] no entry for 0x%x in module id 0x%x (%u entries)\n", address, id,
                         static_cast<unsigned>(table.count));
            return nullptr;
        }
        return it->function;
    }
}

DotrOverlayRegistration::DotrOverlayRegistration(uint32_t id, const DotrOverlayEntry *entries, size_t count)
{
    if (id < kDotrOverlayMaxId)
    {
        dotrOverlayTables()[id] = {entries, count};
    }
    g_ps2OverlayFunctionResolver = resolveDotrOverlay;
}
