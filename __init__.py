# ComfyUI-DetectarTomas  ·  nodo "Detectar tomas (cortes de escena)"
# Si falta PySceneDetect, se instala solo SIN tocar el OpenCV que ya trae Colab.
import importlib, subprocess, sys

def _asegurar_scenedetect():
    try:
        importlib.import_module("scenedetect")
        return
    except Exception:
        pass
    try:
        import cv2  # noqa: F401
        tiene_cv2 = True
    except Exception:
        tiene_cv2 = False
    try:
        if tiene_cv2:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "scenedetect-headless>=0.7.2,<0.8"], check=True)
        else:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "scenedetect-headless>=0.7.2,<0.8"], check=True)
        importlib.invalidate_caches()
        print("[DetectarTomas] PySceneDetect instalado")
    except Exception as e:
        print("[DetectarTomas] No pude instalar PySceneDetect:", e)

_asegurar_scenedetect()

# ComfyUI-DetectarTomas  ·  nodo "Detectar tomas (cortes de escena)"
# Detecta los cortes de cámara de un VIDEO (salida de Load Video del core) con
# PySceneDetect y entrega Usar / Inicio / Fin de hasta 4 tomas.
# Fin es EXCLUSIVO: la toma 1 = frames 0..120 -> Inicio 0, Fin 121.
import bisect
import hashlib
import io
import os
import tempfile

N_TOMAS = 4
UMBRAL_CONTENT = 27.0   # default de ContentDetector
UMBRAL_ADAPTIVE = 3.0   # default de AdaptiveDetector


def _ruta_del_video(video):
    """Devuelve (ruta_en_disco, es_temporal)."""
    src = video.get_stream_source() if hasattr(video, "get_stream_source") else video
    if isinstance(src, (str, os.PathLike)):
        return os.fspath(src), False
    if isinstance(src, io.BytesIO):
        src.seek(0)
        fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="detectar_tomas_")
        with os.fdopen(fd, "wb") as f:
            f.write(src.getbuffer())
        src.seek(0)
        return tmp, True
    raise TypeError(f"Detectar tomas: fuente de video no soportada ({type(src).__name__})")


def _pts_de_frames(ruta):
    """Tiempos (s) de cada frame en orden de presentación, sin decodificar (solo demux)."""
    try:
        import av
    except Exception:
        return None, None
    try:
        with av.open(ruta) as c:
            s = next((x for x in c.streams if x.type == "video"), None)
            if s is None:
                return None, None
            tb = float(s.time_base)
            pts = [float(p.pts) * tb for p in c.demux(s) if p.pts is not None and p.size > 0]
            fps = float(s.average_rate) if s.average_rate else None
        pts.sort()
        if len(pts) > 1:  # fps real = 1 / duración típica de un frame
            d = sorted(b - a for a, b in zip(pts, pts[1:]) if b > a)
            if d:
                fps = 1.0 / d[len(d) // 2]
        return pts, fps
    except Exception:
        return None, None


def _detectar(ruta, detector, umbral, min_frames):
    from scenedetect import open_video, SceneManager, ContentDetector, AdaptiveDetector
    try:
        v = open_video(ruta, backend="pyav")
    except Exception:
        v = open_video(ruta, backend="opencv")
    sm = SceneManager()
    if detector == "adaptive":
        sm.add_detector(AdaptiveDetector(adaptive_threshold=umbral, min_scene_len=min_frames))
    else:
        sm.add_detector(ContentDetector(threshold=umbral, min_scene_len=min_frames))
    sm.detect_scenes(video=v, show_progress=False)
    cortes = [(c.frame_num, c.get_seconds()) for c in sm.get_cut_list()]
    total = int(v.frame_number)
    fps = float(v.frame_rate)
    return cortes, total, fps, type(v).__name__


class DetectarTomas:
    """Nodo original. Entrega las primeras 4 tomas. No se modifica."""
    CATEGORY = "MiniMax H3/Tomas"
    FUNCTION = "detectar"
    OUTPUT_NODE = False
    RETURN_TYPES = tuple(t for _ in range(N_TOMAS) for t in ("BOOLEAN", "INT", "INT")) + ("INT", "STRING")
    RETURN_NAMES = tuple(n for i in range(1, N_TOMAS + 1) for n in (f"usar_{i}", f"inicio_{i}", f"fin_{i}")) + ("num_tomas", "info")
    DESCRIPTION = "Detecta los cortes de cámara del video y entrega Usar/Inicio/Fin (Fin exclusivo) de hasta 4 tomas."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO", {"tooltip": "Conéctalo a la salida VIDEO del Load Video del swap."}),
                "detector": (["content", "adaptive"], {"default": "adaptive",
                             "tooltip": "content = cambio de color/brillo entre frames. adaptive = compara contra el promedio de los frames vecinos."}),
                "umbral": ("FLOAT", {"default": UMBRAL_ADAPTIVE, "min": 0.1, "max": 100.0, "step": 0.1,
                           "tooltip": "Sensibilidad. adaptive: 3.0. content: 27."}),
                "min_frames_toma": ("INT", {"default": 5, "min": 1, "max": 10000, "step": 1,
                                    "tooltip": "Largo mínimo de una toma en frames. Ref2VA necesita al menos 5."}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, video=None, detector="adaptive", umbral=UMBRAL_ADAPTIVE, min_frames_toma=5, **kwargs):
        h = hashlib.sha256(f"{detector}|{umbral}|{min_frames_toma}".encode())
        try:
            if video is not None:
                src = video.get_stream_source()
                if isinstance(src, (str, os.PathLike)):
                    st = os.stat(src)
                    h.update(f"|{os.fspath(src)}|{st.st_mtime_ns}|{st.st_size}".encode())
                elif isinstance(src, io.BytesIO):
                    h.update(hashlib.sha256(src.getbuffer()).digest())
                    src.seek(0)
        except Exception:
            pass
        return h.hexdigest()

    def detectar(self, video, detector="adaptive", umbral=UMBRAL_ADAPTIVE, min_frames_toma=5):
        avisos = []
        if detector == "adaptive" and abs(umbral - UMBRAL_CONTENT) < 1e-6:
            umbral = UMBRAL_ADAPTIVE
            avisos.append("Detector adaptive con umbral 27 (el de content): usé 3.0.")
        ruta, temporal = _ruta_del_video(video)
        try:
            cortes, total_sd, fps_sd, backend = _detectar(ruta, detector, float(umbral), int(min_frames_toma))
            pts, fps_av = _pts_de_frames(ruta)
        finally:
            if temporal:
                try:
                    os.remove(ruta)
                except OSError:
                    pass

        if pts and len(pts) == total_sd:
            t0 = pts[0]
            rel = [p - t0 for p in pts]
            idx = []
            for fn, sec in cortes:
                j = bisect.bisect_left(rel, sec - 1e-4)
                if j > 0 and (j == len(rel) or abs(rel[j - 1] - sec) < abs(rel[j] - sec)):
                    j -= 1
                idx.append(j)
            fps = fps_av or fps_sd
        else:
            rel = None
            idx = [fn for fn, _ in cortes]
            fps = fps_sd
            if pts is not None:
                avisos.append(f"Conteo de frames distinto (PyAV {len(pts)} vs SceneDetect {total_sd}); usé los números de SceneDetect.")
        total = total_sd

        try:
            ini_t, dur_t = video.get_active_trim_window()
        except Exception:
            ini_t, dur_t = 0.0, 0.0
        if (ini_t or dur_t) and rel is not None:
            a = bisect.bisect_left(rel, ini_t - 1e-6)
            b = bisect.bisect_left(rel, ini_t + dur_t - 1e-6) if dur_t else len(rel)
            idx = [i - a for i in idx if a < i < b]
            total = b - a
            avisos.append(f"El video trae recorte (inicio {ini_t:.3f}s, duración {dur_t:.3f}s): frames contados dentro del recorte.")

        limites = [0] + sorted(set(i for i in idx if 0 < i < total)) + [total]
        tomas = [(limites[k], limites[k + 1]) for k in range(len(limites) - 1) if limites[k + 1] > limites[k]]
        if not tomas:
            tomas = [(0, total)]

        fps_txt = f"{fps:.3f}" if fps else "?"
        lineas = [f"Detectar tomas · {detector}, umbral {umbral:g}, min {min_frames_toma} · {total} frames a {fps_txt} fps · {backend}",
                  "Toma | Inicio | Fin (exclusivo) | N frames | segundos"]
        for k, (a, b) in enumerate(tomas, 1):
            seg = f"{(b - a) / fps:.2f}" if fps else "?"
            marca = "" if k <= N_TOMAS else "  (fuera, no se usa)"
            lineas.append(f"{k} | {a} | {b} | {b - a} | {seg}{marca}")
        if len(tomas) > N_TOMAS:
            avisos.append(f"Se detectaron {len(tomas)} tomas; el workflow solo tiene {N_TOMAS}. Solo salen las primeras {N_TOMAS}.")
        cortas = [k for k, (a, b) in enumerate(tomas, 1) if (b - a) < max(5, int(min_frames_toma))]
        if cortas:
            avisos.append("Toma(s) de menos de " + str(max(5, int(min_frames_toma))) + " frames: " + ", ".join(map(str, cortas)) + ".")
        if avisos:
            lineas.append("AVISOS:")
            lineas += ["- " + a for a in avisos]
        info = "\n".join(lineas)
        print(info)

        out = []
        for k in range(N_TOMAS):
            if k < len(tomas):
                a, b = tomas[k]
                out += [True, int(a), int(b)]
            else:
                out += [False, int(total), int(total)]
        out += [min(len(tomas), N_TOMAS), info]
        return tuple(out)


class DetectarTomasBloque:
    """Nueva versión con selector de bloque. Entrega 4 tomas a partir de 'desde_toma'."""
    CATEGORY = "MiniMax H3/Tomas"
    FUNCTION = "detectar"
    OUTPUT_NODE = False
    RETURN_TYPES = tuple(t for _ in range(N_TOMAS) for t in ("BOOLEAN", "INT", "INT")) + ("INT", "STRING")
    RETURN_NAMES = tuple(n for i in range(1, N_TOMAS + 1) for n in (f"usar_{i}", f"inicio_{i}", f"fin_{i}")) + ("num_tomas", "info")
    DESCRIPTION = "Detecta cortes y entrega un bloque de 4 tomas a partir de 'desde_toma'. 1=tomas 1-4, 3=tomas 3-6, etc."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO", {"tooltip": "Conéctalo a la salida VIDEO del Load Video del swap."}),
                "detector": (["content", "adaptive"], {"default": "adaptive",
                             "tooltip": "adaptive se ajusta solo a cada video."}),
                "umbral": ("FLOAT", {"default": UMBRAL_ADAPTIVE, "min": 0.1, "max": 100.0, "step": 0.1,
                           "tooltip": "adaptive: 3.0. content: 27."}),
                "min_frames_toma": ("INT", {"default": 5, "min": 1, "max": 10000, "step": 1,
                                    "tooltip": "Largo mínimo de una toma en frames."}),
                "desde_toma": ("INT", {"default": 1, "min": 1, "max": 100, "step": 1,
                               "tooltip": "Desde qué toma real empezar. 1 = primeras 4. 3 = tomas 3,4,5,6 como espacios 1-4 del workflow."}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, video=None, detector="adaptive", umbral=UMBRAL_ADAPTIVE, min_frames_toma=5, desde_toma=1, **kwargs):
        h = hashlib.sha256(f"{detector}|{umbral}|{min_frames_toma}|{desde_toma}".encode())
        try:
            if video is not None:
                src = video.get_stream_source()
                if isinstance(src, (str, os.PathLike)):
                    st = os.stat(src)
                    h.update(f"|{os.fspath(src)}|{st.st_mtime_ns}|{st.st_size}".encode())
                elif isinstance(src, io.BytesIO):
                    h.update(hashlib.sha256(src.getbuffer()).digest())
                    src.seek(0)
        except Exception:
            pass
        return h.hexdigest()

    def detectar(self, video, detector="adaptive", umbral=UMBRAL_ADAPTIVE, min_frames_toma=5, desde_toma=1):
        avisos = []
        if detector == "adaptive" and abs(umbral - UMBRAL_CONTENT) < 1e-6:
            umbral = UMBRAL_ADAPTIVE
            avisos.append("Detector adaptive con umbral 27: usé 3.0.")
        ruta, temporal = _ruta_del_video(video)
        try:
            cortes, total_sd, fps_sd, backend = _detectar(ruta, detector, float(umbral), int(min_frames_toma))
            pts, fps_av = _pts_de_frames(ruta)
        finally:
            if temporal:
                try:
                    os.remove(ruta)
                except OSError:
                    pass

        if pts and len(pts) == total_sd:
            t0 = pts[0]
            rel = [p - t0 for p in pts]
            idx = []
            for fn, sec in cortes:
                j = bisect.bisect_left(rel, sec - 1e-4)
                if j > 0 and (j == len(rel) or abs(rel[j - 1] - sec) < abs(rel[j] - sec)):
                    j -= 1
                idx.append(j)
            fps = fps_av or fps_sd
        else:
            rel = None
            idx = [fn for fn, _ in cortes]
            fps = fps_sd
            if pts is not None:
                avisos.append(f"Conteo de frames distinto; usé SceneDetect.")
        total = total_sd

        try:
            ini_t, dur_t = video.get_active_trim_window()
        except Exception:
            ini_t, dur_t = 0.0, 0.0
        if (ini_t or dur_t) and rel is not None:
            a = bisect.bisect_left(rel, ini_t - 1e-6)
            b = bisect.bisect_left(rel, ini_t + dur_t - 1e-6) if dur_t else len(rel)
            idx = [i - a for i in idx if a < i < b]
            total = b - a
            avisos.append(f"Video con recorte: frames contados dentro del recorte.")

        limites = [0] + sorted(set(i for i in idx if 0 < i < total)) + [total]
        tomas = [(limites[k], limites[k + 1]) for k in range(len(limites) - 1) if limites[k + 1] > limites[k]]
        if not tomas:
            tomas = [(0, total)]

        desde = max(1, int(desde_toma))
        inicio_idx = desde - 1
        bloque = tomas[inicio_idx:inicio_idx + N_TOMAS]
        total_detectadas = len(tomas)

        fps_txt = f"{fps:.3f}" if fps else "?"
        lineas = [
            f"Detectar tomas (bloque) · {detector}, umbral {umbral:g}, min {min_frames_toma} · {total} frames a {fps_txt} fps",
            f"Bloque: desde toma real {desde} → espacios 1-{N_TOMAS} del workflow",
            "Espacio | Toma real | Inicio | Fin (exclusivo) | N frames | segundos"
        ]
        for i in range(N_TOMAS):
            real = desde + i
            if i < len(bloque):
                a, b = bloque[i]
                seg = f"{(b - a) / fps:.2f}" if fps else "?"
                lineas.append(f"{i+1} | {real} | {a} | {b} | {b - a} | {seg}")
            else:
                lineas.append(f"{i+1} | (no existe) | - | - | - | -")

        if total_detectadas > inicio_idx + N_TOMAS:
            avisos.append(f"Hay {total_detectadas} tomas. Este bloque usa de la {desde} a la {desde + len(bloque) - 1}.")
        elif total_detectadas < desde:
            avisos.append(f"Solo hay {total_detectadas} tomas. desde_toma={desde} queda fuera.")
        else:
            avisos.append(f"Total: {total_detectadas}. Bloque {desde} a {desde + len(bloque) - 1}.")

        if avisos:
            lineas.append("AVISOS:")
            lineas += ["- " + a for a in avisos]
        info = "\n".join(lineas)
        print(info)

        out = []
        for i in range(N_TOMAS):
            if i < len(bloque):
                a, b = bloque[i]
                out += [True, int(a), int(b)]
            else:
                out += [False, int(total), int(total)]
        out += [len(bloque), info]
        return tuple(out)


NODE_CLASS_MAPPINGS = {
    "DetectarTomas": DetectarTomas,
    "DetectarTomasBloque": DetectarTomasBloque,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DetectarTomas": "Detectar tomas (cortes de escena)",
    "DetectarTomasBloque": "Detectar tomas · bloque (desde N)",
}
