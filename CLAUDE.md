# Contexto para sessões novas

Recomp de Yu-Gi-Oh! The Duelists of the Roses (PS2, USA, `SLUS_205.15`) com PS2Recomp. Ver README.md para layout.
Responder em português.

## Regras
- Nada do jogo no git: ISO, ELF, IRX, código gerado. Ficam em `../dotr/`.
- Correções genéricas no PS2Recomp viram arquivo em `patches/` (o upstream tem 132 PRs abertos e aceita ~3/mês; não
  depender dele). Correção específica do DotR vai em `src/`.
- Nunca reativar os patches de "Potential self-modifying code" que o `ps2_analyzer` sugere (viram NOP). No God of War
  eram `sw` comuns em `.data` WAX e quebravam o carregamento. Os 21 do DotR já foram removidos do `config/dotr.toml`.

## O que já se sabe do ELF (2026-10-20)
- Entry 0x100008. Código+dados num PT_LOAD em 0x100000, filesz 0x20FF00, memsz 0x251300.
- Sem símbolos (`.symtab` vazia apesar de `file` dizer "not stripped").
- 834 segmentos LOAD extras, todos em 0x01E00000, filesz 0, memsz 0x100–0x7000, seções sem nome.
  **Natureza não verificada**: podem ser overlays de código carregados do disco, microcódigo VU ou artefato do linker.
- IOP: PADMAN, MCMAN/MCSERV, LIBSD, SDRDRV, SIO2MAN, KCEJEAST (módulo da Konami), IOPRP.IMG.
- `ps2_analyzer` (fallback sem Ghidra): 263 funções de lib p/ stub, 293 sem handler no runtime, 6 jump tables.

## Referência: God of War PS2 (jogável, out/2026)
`../Tobiichi-Port` (clone). Docs úteis em `docs/waffle/`, principalmente `elf-and-recompilation.md` e
`runtime-changes.md`. Pipeline do KIexster: github.com/KIexster/god-of-war-recomp (68 patches em `patches/`).
- Descoberta de funções deles (find_functions.py, 6482 funções): alvos de JAL + ponteiros em .data/.rodata para .text
  + pares lui/addiu|ori, só se caírem em fronteira (depois de `jr $ra`/tail `j` + delay slot), menos runs que parecem
  jump table. Adaptar para o DotR é o próximo passo.
- Bugs do recompilador que eles corrigiram: branches 64-bit testando 32, SQRT.S/RSQRT.S/DIV.S, CVT.W.S truncando.
  Parte já está no upstream (#272).
- Runtime reservava pools dentro do heap do jogo → corrupção; eles realocaram via `GuestReservedLayout`.

## Próximos passos
1. Tools de função (estilo find_functions.py) → `config/funcmap.csv`, setar `ghidra_output` no toml.
2. Rodar `ps2_recomp config/dotr.toml`, depois compilar com o runtime.
3. Descobrir o que são os 834 segmentos em 0x01E00000.
4. Avaliar aplicar os patches do KIexster / PRs abertos genéricos (lfsayrn, danfreitas97, abilliontokens).
