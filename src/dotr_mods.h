#pragma once
// Optional DotR gameplay mods, switched on from the launcher, a flag or the config file.
class PS2Runtime;

// #72: duel any opponent whatever the deck costs (the map refuses when your deck's DC is above the opponent's).
void dotrInstallNoDeckCostLimit(PS2Runtime &runtime);
