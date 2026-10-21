#pragma once
// DotR overlay modules (DATA/CMODULE/BMODULE/MMODULE.MRG), all loaded at 0x1E00000 and recompiled one by one by
// tools/overlays.py. Each generated ov_<name>.cpp registers its sorted entry table under the module id.
#include "ps2_runtime_core.h"
#include <cstddef>

struct DotrOverlayEntry
{
    uint32_t address;
    PS2Runtime::RecompiledFunction function;
};

struct DotrOverlayRegistration
{
    DotrOverlayRegistration(uint32_t id, const DotrOverlayEntry *entries, size_t count);
};
