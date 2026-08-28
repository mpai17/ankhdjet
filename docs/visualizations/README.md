# Visualizations

Interactive, self-contained HTML explainers of the architecture. Each file is a
single page with no build step and no dependencies (fonts load from Google Fonts
when online, and fall back cleanly offline). Open any `.html` in a browser, or
host the folder with a static server or GitHub Pages.

| File | What it shows |
| --- | --- |
| `nor_tile_dataflow.html` | Step-through animation of the bit-serial matrix-vector read inside `cirom_nor_tile`: one-hot wordline sweep, per-column BL+/BL- hits for +1/-1/0 weights, and the shift-and-add accumulation over activation bit-planes, landing on the exact signed dot product. |
| `between_layer_requantize.html` | The combinational `between_layer` seam: one tile's raw signed accumulators pass through multiply-by-scale, arithmetic shift, ReLU, and saturating clip to become the next tile's low-bit input activations, with no register or SRAM between the two layers. |
