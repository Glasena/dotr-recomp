# dotr-recomp — Yu-Gi-Oh! The Duelists of the Roses (PS2)

Recompilação estática de **Yu-Gi-Oh! The Duelists of the Roses** (PS2, NTSC-U `SLUS-20515`) para PC/Linux com o
[PS2Recomp](https://github.com/ran-j/PS2Recomp). Estado: **explorando**, ainda não roda.

Este repositório **não contém** arquivos do jogo (ISO, ELF, IRX, dados) nem código C++ gerado a partir deles.
Você precisa da **sua própria cópia** do jogo.

## Layout

```text
workspace/
  PS2Recomp/      clone de https://github.com/ran-j/PS2Recomp + patches/ aplicados
  dotr/           SLUS_205.15 e SYSTEM.CNF extraídos do seu disco (fora do git)
  dotr-recomp/    este repositório
    patches/      correções no PS2Recomp, aplicadas em ordem
    config/       dotr.toml (config do recompilador)
    src/          overrides do jogo
    tools/        iso9660.py (extrai arquivos da raiz do ISO, só stdlib)
    docs/         notas
```

## Passos

```bash
# 1. extrair o ELF do seu ISO
mkdir -p ../dotr
python3 tools/iso9660.py "/caminho/do/seu.iso" ../dotr SYSTEM.CNF SLUS_205.15

# 2. PS2Recomp com os patches
git clone https://github.com/ran-j/PS2Recomp.git ../PS2Recomp
git -C ../PS2Recomp apply "$PWD"/patches/*.patch
cmake -S ../PS2Recomp -B ../PS2Recomp/out/build-tools -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPS2X_BUILD_RUNTIME=OFF -DPS2X_BUILD_STUDIO=OFF -DPS2X_BUILD_TEST=OFF
cmake --build ../PS2Recomp/out/build-tools

# 3. gerar o C++ (rodar a partir desta pasta: os caminhos do toml são relativos a ela)
../PS2Recomp/out/build-tools/ps2xRecomp/ps2_recomp config/dotr.toml
```

O runtime (`ps2xRuntime`) no Ubuntu precisa de `libxinerama-dev` e `libasound2-dev`.

## Licença

GPL-3.0, como o PS2Recomp. Yu-Gi-Oh! é marca da Konami; projeto sem fins comerciais e sem afiliação.
