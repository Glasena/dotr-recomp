// DotR runner entry point (#62): command-line flags, a config file in the user's config dir, a small raylib launcher
// (disc, memory card folder, window size, controls, GS backend override) and one-time ISO extraction.
// Replaces PS2Recomp's ps2xRuntime/src/main.cpp (tools/sync_runner.sh copies it to src/runner/main.cpp).
// Test mode (PS2X_HEADLESS=1, tools/test_run.sh) reads no config file and shows no launcher, so its runs stay as
// before: the runtime's own defaults (CPU GS, <elf dir>/mc0) apply unless a flag says otherwise.
#include "dotr_mods.h"
#include "ps2_runtime.h"
#include "ps2_host_backend.h"
#include "runtime/ps2_pad.h"
#include "runtime/ps2_test_mode.h"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace
{
    constexpr const char *kElfName = "SLUS_205.15";
    constexpr const char *kTitle = "Yu-Gi-Oh! The Duelists of the Roses";

    struct Options
    {
        std::string disc;      // ISO, extracted folder or the ELF itself
        std::string memcardDir; // holds mc0/ and mc1/
        std::string gsBackend; // auto | pgs | cpu ("" = leave PS2X_GS_BACKEND alone)
        int width = 1920;
        int height = 1080;
        bool noLauncher = false;
        bool noDeckCostLimit = false; // #72 mod
    };

    std::string envOr(const char *name, const std::string &fallback)
    {
        const char *v = std::getenv(name);
        return v && *v ? v : fallback;
    }

    fs::path configFile()
    {
        const std::string xdg = envOr("XDG_CONFIG_HOME", "");
        return (xdg.empty() ? fs::path(envOr("HOME", ".")) / ".config" : fs::path(xdg)) / "dotr-recomp" / "config.cfg";
    }

    fs::path cacheDir()
    {
        const std::string xdg = envOr("XDG_CACHE_HOME", "");
        return (xdg.empty() ? fs::path(envOr("HOME", ".")) / ".cache" : fs::path(xdg)) / "dotr-recomp";
    }

    fs::path executableDir(const char *argv0)
    {
        std::error_code ec;
        fs::path exe = fs::read_symlink("/proc/self/exe", ec);
        if (ec)
            exe = fs::absolute(argv0, ec);
        return exe.parent_path();
    }

    std::map<std::string, std::string> loadConfig()
    {
        std::map<std::string, std::string> cfg;
        std::ifstream in(configFile());
        for (std::string line; std::getline(in, line);)
        {
            const size_t eq = line.find('=');
            if (line.empty() || line[0] == '#' || eq == std::string::npos)
                continue;
            cfg[line.substr(0, eq)] = line.substr(eq + 1);
        }
        return cfg;
    }

    bool parseSize(const std::string &s, int &w, int &h)
    {
        int a = 0, b = 0;
        char x = 0;
        std::istringstream in(s);
        if (!(in >> a >> x >> b) || (x != 'x' && x != 'X') || a < 160 || b < 120)
            return false;
        w = a;
        h = b;
        return true;
    }

    // bind.<button>=<key1>,<key2>,<gamepad button> (raylib KeyboardKey / GamepadButton numbers, 0 = none)
    void loadBindings(const std::map<std::string, std::string> &cfg)
    {
        for (int bit = 0; bit < ps2x::pad::kButtonCount; ++bit)
        {
            auto it = cfg.find(std::string("bind.") + ps2x::pad::buttonName(bit));
            if (it == cfg.end())
                continue;
            ps2x::pad::Binding b{};
            if (std::sscanf(it->second.c_str(), "%d,%d,%d", &b.keys[0], &b.keys[1], &b.button) == 3)
                ps2x::pad::binding(bit) = b;
        }
    }

    void saveConfig(const Options &o)
    {
        std::error_code ec;
        fs::create_directories(configFile().parent_path(), ec);
        std::ofstream out(configFile());
        out << "# dotr-recomp launcher settings\n"
            << "disc=" << o.disc << "\nmemcard_dir=" << o.memcardDir << "\ngs_backend=" << o.gsBackend
            << "\nwindow=" << o.width << "x" << o.height << "\nmod.no_deck_cost=" << o.noDeckCostLimit << "\n";
        for (int bit = 0; bit < ps2x::pad::kButtonCount; ++bit)
        {
            const ps2x::pad::Binding &b = ps2x::pad::binding(bit);
            out << "bind." << ps2x::pad::buttonName(bit) << "=" << b.keys[0] << "," << b.keys[1] << "," << b.button
                << "\n";
        }
    }

    bool isIso(const fs::path &p)
    {
        std::ifstream f(p, std::ios::binary);
        char magic[6]{};
        f.seekg(16 * 2048);
        return f.read(magic, 6) && std::memcmp(magic + 1, "CD001", 5) == 0;
    }

    // ISO 9660 extraction, the logic of tools/iso9660.py --all. The runtime serves cdrom0: from a host folder (file
    // opens, sceCdSearchFile and the IOP loader all resolve paths there), so a one-time extraction is much smaller
    // than teaching every one of those paths to read inside an image.
    bool extractTree(std::ifstream &f, uint32_t lba, uint32_t size, const fs::path &out)
    {
        fs::create_directories(out);
        std::vector<uint8_t> dir(size);
        f.seekg(static_cast<std::streamoff>(lba) * 2048);
        if (!f.read(reinterpret_cast<char *>(dir.data()), size))
            return false;
        for (size_t i = 0; i < dir.size();)
        {
            const uint8_t n = dir[i];
            if (n == 0) // records never span sectors; skip the padding
            {
                i = (i / 2048 + 1) * 2048;
                continue;
            }
            if (i + n > dir.size() || n < 34)
                return false;
            const uint8_t *r = dir.data() + i;
            uint32_t ext, sz;
            std::memcpy(&ext, r + 2, 4);
            std::memcpy(&sz, r + 10, 4);
            std::string name(reinterpret_cast<const char *>(r + 33), r[32]);
            name = name.substr(0, name.find(';'));
            i += n;
            if (name.empty() || name == std::string(1, '\0') || name == "\x01" || name.find('/') != std::string::npos ||
                name == "." || name == "..")
                continue;
            if (r[25] & 2)
            {
                if (!extractTree(f, ext, sz, out / name))
                    return false;
                continue;
            }
            std::ofstream o(out / name, std::ios::binary);
            f.seekg(static_cast<std::streamoff>(ext) * 2048);
            std::vector<char> buf(1 << 20);
            for (uint32_t left = sz; left;)
            {
                const uint32_t chunk = std::min<uint32_t>(left, buf.size());
                if (!f.read(buf.data(), chunk) || !o.write(buf.data(), chunk))
                    return false;
                left -= chunk;
            }
        }
        return true;
    }

    // Disc path -> ELF path. Folder: <dir>/SLUS_205.15. ISO: extracted once to <cache>/disc (re-extracted when the
    // image path or size changes). Anything else is taken as the ELF. Empty on error (message in err).
    fs::path resolveDisc(const std::string &disc, std::string &err)
    {
        std::error_code ec;
        const fs::path p = fs::absolute(disc, ec);
        if (disc.empty() || !fs::exists(p))
        {
            err = "disc not found: " + disc;
            return {};
        }
        if (fs::is_directory(p))
        {
            if (fs::exists(p / kElfName))
                return p / kElfName;
            err = "no " + std::string(kElfName) + " in " + p.string() + " (is this the USA disc?)";
            return {};
        }
        if (!isIso(p))
            return p;

        const fs::path out = cacheDir() / "disc";
        const std::string stamp = p.string() + "\n" + std::to_string(fs::file_size(p, ec)) + "\n";
        std::ifstream stampIn(out / ".source");
        std::stringstream old;
        old << stampIn.rdbuf();
        if (old.str() == stamp && fs::exists(out / kElfName))
            return out / kElfName;

        std::cerr << "[launcher] extracting " << p << " to " << out << std::endl;
        fs::remove_all(out, ec);
        std::ifstream f(p, std::ios::binary);
        std::vector<char> pvd(2048);
        f.seekg(16 * 2048);
        f.read(pvd.data(), pvd.size());
        uint32_t lba, size;
        std::memcpy(&lba, pvd.data() + 156 + 2, 4);
        std::memcpy(&size, pvd.data() + 156 + 10, 4);
        if (!extractTree(f, lba, size, out) || !fs::exists(out / kElfName))
        {
            err = "could not extract " + p.string() + " (or it has no " + kElfName + ")";
            return {};
        }
        std::ofstream(out / ".source") << stamp;
        return out / kElfName;
    }

    // ---- launcher -------------------------------------------------------------------------------------------------

    std::string keyName(int k)
    {
        if (k <= 0)
            return "-";
        if ((k >= KEY_A && k <= KEY_Z) || (k >= KEY_ZERO && k <= KEY_NINE))
            return std::string(1, static_cast<char>(k));
        switch (k)
        {
        case KEY_SPACE: return "Space";
        case KEY_ENTER: return "Enter";
        case KEY_TAB: return "Tab";
        case KEY_ESCAPE: return "Esc";
        case KEY_BACKSPACE: return "Backspace";
        case KEY_UP: return "Up";
        case KEY_DOWN: return "Down";
        case KEY_LEFT: return "Left";
        case KEY_RIGHT: return "Right";
        case KEY_LEFT_SHIFT: return "LShift";
        case KEY_RIGHT_SHIFT: return "RShift";
        case KEY_LEFT_CONTROL: return "LCtrl";
        case KEY_RIGHT_CONTROL: return "RCtrl";
        case KEY_LEFT_ALT: return "LAlt";
        case KEY_RIGHT_ALT: return "RAlt";
        default:
            if (k >= KEY_KP_0 && k <= KEY_KP_9)
                return "KP" + std::to_string(k - KEY_KP_0);
            if (k >= KEY_F1 && k <= KEY_F12)
                return "F" + std::to_string(k - KEY_F1 + 1);
            return "key " + std::to_string(k);
        }
    }

    const char *padButtonName(int b)
    {
        static const char *names[] = {"-", "LFace Up", "LFace Right", "LFace Down", "LFace Left", "RFace Up (Y/Tri)",
                                      "RFace Right (B/Cir)", "RFace Down (A/Cross)", "RFace Left (X/Sq)", "LB", "LT",
                                      "RB", "RT", "Back/Select", "Guide", "Start", "L-stick click", "R-stick click"};
        return b >= 0 && b < 18 ? names[b] : "?";
    }

    struct Ui
    {
        int focus = -1; // text field index with keyboard focus
        int fieldIndex = 0;
        bool clicked(Rectangle r) const
        {
            return IsMouseButtonPressed(MOUSE_BUTTON_LEFT) && CheckCollisionPointRec(GetMousePosition(), r);
        }
        bool button(Rectangle r, const std::string &label)
        {
            const bool hot = CheckCollisionPointRec(GetMousePosition(), r);
            DrawRectangleRec(r, hot ? Color{90, 90, 140, 255} : Color{60, 60, 90, 255});
            DrawText(label.c_str(), static_cast<int>(r.x) + 10, static_cast<int>(r.y + r.height / 2) - 10, 20, RAYWHITE);
            return clicked(r);
        }
        void field(Rectangle r, std::string &text)
        {
            const int me = fieldIndex++;
            if (clicked(r))
                focus = me;
            const bool active = focus == me;
            DrawRectangleRec(r, active ? Color{40, 40, 60, 255} : Color{30, 30, 40, 255});
            DrawRectangleLinesEx(r, 1, active ? SKYBLUE : GRAY);
            if (active)
            {
                for (int c = GetCharPressed(); c > 0; c = GetCharPressed())
                    if (c >= 32 && c < 127)
                        text += static_cast<char>(c);
                if ((IsKeyPressed(KEY_BACKSPACE) || IsKeyPressedRepeat(KEY_BACKSPACE)) && !text.empty())
                    text.pop_back();
                if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_RIGHT_CONTROL)) && IsKeyPressed(KEY_V))
                    if (const char *clip = GetClipboardText())
                        text += clip;
            }
            // show the tail of long paths
            std::string shown = text + (active && (static_cast<int>(GetTime() * 2) & 1) ? "_" : "");
            while (shown.size() > 1 && MeasureText(shown.c_str(), 20) > r.width - 16)
                shown.erase(0, 1);
            BeginScissorMode(static_cast<int>(r.x), static_cast<int>(r.y), static_cast<int>(r.width),
                             static_cast<int>(r.height));
            DrawText(shown.c_str(), static_cast<int>(r.x) + 8, static_cast<int>(r.y + r.height / 2) - 10, 20,
                     RAYWHITE);
            EndScissorMode();
        }
    };

    // Returns false when the user quits.
    bool runLauncher(Options &o)
    {
        InitWindow(900, 620, "dotr-recomp launcher");
        SetExitKey(KEY_NULL);
        SetTargetFPS(60);
        Ui ui;
        std::string size = std::to_string(o.width) + "x" + std::to_string(o.height);
        std::string status;
        bool controls = false;
        int capRow = -1, capCol = -1; // binding being captured: column 0/1 key, 2 gamepad button
        bool start = false;
        const char *backends[] = {"auto", "pgs", "cpu"};

        while (!WindowShouldClose() && !start)
        {
            if (IsFileDropped())
            {
                FilePathList dropped = LoadDroppedFiles();
                if (dropped.count > 0)
                    o.disc = dropped.paths[0];
                UnloadDroppedFiles(dropped);
            }
            BeginDrawing();
            ClearBackground(Color{20, 20, 28, 255});
            ui.fieldIndex = 0;
            if (!controls)
            {
                DrawText(kTitle, 30, 20, 26, GOLD);
                DrawText("Disc: your own ISO or the extracted disc folder (drag a file onto this window)", 30, 70,
                         18, LIGHTGRAY);
                ui.field({30, 95, 840, 36}, o.disc);
                DrawText("Memory card folder (mc0/ and mc1/ are created in it)", 30, 145, 18, LIGHTGRAY);
                ui.field({30, 170, 840, 36}, o.memcardDir);
                DrawText("Window size (the 640x448 picture is scaled, aspect kept)", 30, 220, 18, LIGHTGRAY);
                ui.field({30, 245, 200, 36}, size);
                if (ui.button({30, 305, 200, 40}, "Controls..."))
                    controls = true, ui.focus = -1;
                DrawText("Advanced", 30, 370, 20, GRAY);
                DrawText("GS backend (auto = GPU paraLLEl-GS if Vulkan works, else CPU):", 30, 400, 18, LIGHTGRAY);
                int cur = 0;
                for (int i = 0; i < 3; ++i)
                    if (o.gsBackend == backends[i])
                        cur = i;
                if (ui.button({30, 425, 120, 36}, backends[cur]))
                    o.gsBackend = backends[(cur + 1) % 3];
                DrawText("Mods", 470, 370, 20, GRAY);
                DrawText("Duel any opponent, whatever your deck costs:", 470, 400, 18, LIGHTGRAY);
                if (ui.button({470, 425, 120, 36}, o.noDeckCostLimit ? "on" : "off"))
                    o.noDeckCostLimit = !o.noDeckCostLimit;
                if (ui.button({30, 520, 160, 50}, "Start"))
                {
                    std::string err;
                    if (!parseSize(size, o.width, o.height))
                        status = "window size must look like 1920x1080";
                    else if (resolveDisc(o.disc, err).empty()) // extracts an ISO once (a few seconds)
                        status = err;
                    else
                        start = true;
                }
                if (ui.button({210, 520, 120, 50}, "Quit"))
                    break;
                DrawText(status.c_str(), 350, 537, 18, ORANGE);
            }
            else
            {
                DrawText("Controls (click a cell, then press a key / gamepad button; Backspace clears, Esc cancels)",
                         20, 12, 16, LIGHTGRAY);
                const int gp = IsGamepadAvailable(0) ? 0 : -1;
                const std::string padInfo =
                    gp >= 0 ? std::string("Gamepad 0: ") + GetGamepadName(0) + TextFormat("  L(%.2f, %.2f)  R(%.2f, %.2f)",
                                                                                         GetGamepadAxisMovement(0, GAMEPAD_AXIS_LEFT_X),
                                                                                         GetGamepadAxisMovement(0, GAMEPAD_AXIS_LEFT_Y),
                                                                                         GetGamepadAxisMovement(0, GAMEPAD_AXIS_RIGHT_X),
                                                                                         GetGamepadAxisMovement(0, GAMEPAD_AXIS_RIGHT_Y))
                            : std::string("No gamepad detected (sticks map to the left/right analog sticks)");
                DrawText(padInfo.c_str(), 20, 34, 16, gp >= 0 ? GREEN : GRAY);
                DrawText("Button", 20, 58, 18, GRAY);
                DrawText("Key 1", 170, 58, 18, GRAY);
                DrawText("Key 2", 340, 58, 18, GRAY);
                DrawText("Gamepad", 510, 58, 18, GRAY);
                // PS2 order for display
                const int order[] = {4, 6, 7, 5, 14, 13, 15, 12, 10, 11, 8, 9, 1, 2, 3, 0};
                for (int row = 0; row < ps2x::pad::kButtonCount; ++row)
                {
                    const int bit = order[row];
                    ps2x::pad::Binding &b = ps2x::pad::binding(bit);
                    const float y = 82.0f + row * 29.0f;
                    DrawText(ps2x::pad::buttonName(bit), 20, static_cast<int>(y) + 4, 18, RAYWHITE);
                    for (int col = 0; col < 3; ++col)
                    {
                        const Rectangle r{170.0f + col * 170.0f, y, col == 2 ? 230.0f : 160.0f, 26.0f};
                        const bool cap = capRow == row && capCol == col;
                        const std::string label = cap ? "press..." : col < 2 ? keyName(b.keys[col]) : padButtonName(b.button);
                        DrawRectangleRec(r, cap ? Color{120, 80, 40, 255} : Color{45, 45, 65, 255});
                        DrawText(label.c_str(), static_cast<int>(r.x) + 6, static_cast<int>(y) + 4, 16, RAYWHITE);
                        if (ui.clicked(r))
                        {
                            capRow = row;
                            capCol = col;
                            while (GetKeyPressed() != 0)
                            {
                            }
                        }
                        if (!cap)
                            continue;
                        if (col < 2)
                        {
                            const int k = GetKeyPressed();
                            if (k == KEY_ESCAPE)
                                capRow = -1;
                            else if (k == KEY_BACKSPACE)
                                b.keys[col] = 0, capRow = -1;
                            else if (k > 0)
                                b.keys[col] = k, capRow = -1;
                        }
                        else
                        {
                            const int k = GetKeyPressed();
                            const int pb = GetGamepadButtonPressed();
                            if (k == KEY_ESCAPE)
                                capRow = -1;
                            else if (k == KEY_BACKSPACE)
                                b.button = 0, capRow = -1;
                            else if (pb > 0)
                                b.button = pb, capRow = -1;
                        }
                    }
                }
                if (ui.button({760, 82, 120, 36}, "Defaults"))
                    ps2x::pad::resetBindings();
                if (ui.button({760, 130, 120, 36}, "Back"))
                    controls = false, capRow = -1;
            }
            EndDrawing();
        }
        CloseWindow();
        return start;
    }

    void usage()
    {
        std::cout << "usage: ps2EntryRunner [options] [disc]\n"
                     "  disc                   your ISO, the extracted disc folder, or its SLUS_205.15\n"
                     "  --memcard-dir DIR      memory card folder (default: saves/ next to the executable)\n"
                     "  --gs-backend B         auto | pgs | cpu (default auto: pgs if Vulkan works)\n"
                     "  --window WxH           window size (default 1920x1080)\n"
                     "  --no-launcher          start the game directly\n"
                     "  --no-deck-cost-limit   mod: duel any opponent whatever your deck costs\n"
                     "Settings chosen in the launcher are kept in " << configFile().string() << "\n";
    }
}

int main(int argc, char *argv[])
{
    std::set_terminate([]()
                       {
                           std::cerr << "[terminate] unhandled exception" << std::endl;
                           if (std::exception_ptr ep = std::current_exception())
                           {
                               try { std::rethrow_exception(ep); }
                               catch (const std::exception &e) { std::cerr << "[terminate] " << e.what() << std::endl; }
                               catch (...) {}
                           }
                           std::abort(); });
    try
    {
        const bool testMode = ps2x::test::headless();
        Options o;
        if (!testMode)
        {
            const auto cfg = loadConfig();
            auto get = [&](const char *k, const std::string &def)
            {
                auto it = cfg.find(k);
                return it != cfg.end() && !it->second.empty() ? it->second : def;
            };
            o.disc = get("disc", "");
            o.memcardDir = get("memcard_dir", (executableDir(argv[0]) / "saves").string());
            o.gsBackend = get("gs_backend", "auto");
            parseSize(get("window", ""), o.width, o.height);
            o.noDeckCostLimit = get("mod.no_deck_cost", "0") == "1";
            loadBindings(cfg);
        }
        o.gsBackend = envOr("PS2X_GS_BACKEND", o.gsBackend); // env wins over the config file

        bool sizeFlag = false;
        for (int i = 1; i < argc; ++i)
        {
            const std::string a = argv[i];
            auto next = [&]() -> std::string
            {
                if (i + 1 >= argc)
                    throw std::runtime_error("missing value for " + a);
                return argv[++i];
            };
            if (a == "--help" || a == "-h")
                return usage(), 0;
            else if (a == "--no-launcher")
                o.noLauncher = true;
            else if (a == "--no-deck-cost-limit")
                o.noDeckCostLimit = true;
            else if (a == "--memcard-dir")
                o.memcardDir = next();
            else if (a == "--gs-backend")
                o.gsBackend = next();
            else if (a == "--window")
            {
                if (!parseSize(next(), o.width, o.height))
                    throw std::runtime_error("--window wants WxH, e.g. 1920x1080");
                sizeFlag = true;
            }
            else if (a.rfind("--", 0) == 0)
                throw std::runtime_error("unknown option " + a + " (see --help)");
            else
                o.disc = a;
        }
        if (!o.gsBackend.empty() && o.gsBackend != "auto" && o.gsBackend != "pgs" && o.gsBackend != "cpu")
            throw std::runtime_error("--gs-backend must be auto, pgs or cpu");

        if (!testMode && !o.noLauncher)
        {
            if (!runLauncher(o))
                return 0;
            saveConfig(o);
        }

        std::string err;
        const fs::path elf = resolveDisc(o.disc, err);
        if (elf.empty())
        {
            std::cerr << "[launcher] " << err << std::endl;
            usage();
            return 1;
        }
        if (!o.gsBackend.empty())
            setenv("PS2X_GS_BACKEND", o.gsBackend.c_str(), 1);

        PS2Runtime runtime;
        if (!runtime.initialize(kTitle))
        {
            std::cerr << "Failed to initialize PS2 runtime" << std::endl;
            return 1;
        }
        if (!testMode || sizeFlag)
        {
            const int m = GetCurrentMonitor();
            const int w = std::min(o.width, GetMonitorWidth(m) > 0 ? GetMonitorWidth(m) : o.width);
            const int h = std::min(o.height, GetMonitorHeight(m) > 0 ? GetMonitorHeight(m) : o.height);
            SetWindowSize(w, h);
            SetWindowPosition((GetMonitorWidth(m) - w) / 2, (GetMonitorHeight(m) - h) / 2);
        }
        if (!o.memcardDir.empty()) // before loadELF, which keeps it (loading already creates the card folders)
        {
            PS2Runtime::IoPaths paths = PS2Runtime::getIoPaths();
            paths.mcRoot = fs::absolute(o.memcardDir) / "mc0";
            std::error_code ec;
            fs::create_directories(paths.mcRoot, ec);
            fs::create_directories(paths.mcRoot.parent_path() / "mc1", ec);
            PS2Runtime::setIoPaths(paths);
            std::cerr << "[launcher] memory cards in " << paths.mcRoot.parent_path() << std::endl;
        }

        if (!runtime.loadELF(elf.string()))
        {
            std::cerr << "Failed to load ELF file: " << elf << std::endl;
            return 1;
        }

        if (o.noDeckCostLimit)
            dotrInstallNoDeckCostLimit(runtime);
        runtime.run();
        std::cout.flush();
        std::cerr.flush();
        std::_Exit(0);
    }
    catch (const std::exception &e)
    {
        std::cerr << "[main] fatal: " << e.what() << std::endl;
    }
    std::cout.flush();
    std::cerr.flush();
    std::_Exit(1);
}
