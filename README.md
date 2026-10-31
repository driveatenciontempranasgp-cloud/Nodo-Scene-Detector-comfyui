# ComfyUI-DetectarTomas

Nodo **Detectar tomas (cortes de escena)** para ComfyUI (categoría `MiniMax H3/Tomas`).

Recibe el `VIDEO` del Load Video del core, detecta los cortes de cámara con PySceneDetect y entrega `usar`, `inicio` y `fin` (Fin exclusivo) de hasta 4 tomas, más `num_tomas` e `info` (tabla de tomas y avisos).

- Detector `content`, umbral 27 por defecto (`adaptive`: 3.0).
- `min_frames_toma`: 5 por defecto (Ref2VA necesita al menos 5).
- Lee el video frame por frame, sin cargarlo entero en memoria.
- Si falta PySceneDetect lo instala solo sin reemplazar el OpenCV existente.

Instalación: `git clone` en `ComfyUI/custom_nodes` y `pip install -r requirements.txt`.
