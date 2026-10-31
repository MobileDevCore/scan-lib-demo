import ctypes
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any


class ScanMatchError(RuntimeError):
    """Base exception for ScanMatch C library errors."""
    def __init__(self, message: str, code: str = "PROCESSING_ERROR"):
        super().__init__(message)
        self.code = code


class ScanMatch:
    """Python ctypes FFI wrapper for ScanMatch C library (build/libscanmatch.so).
    
    Safe memory management: Every C-allocated JSON buffer is guaranteed
    to be freed via sm_free_string in a finally block.
    """

    def __init__(self, library_path: Optional[os.PathLike] = None):
        # Resolve build directory relative to this file without hardcoded paths
        root_dir = Path(__file__).resolve().parents[1]
        build_dir = root_dir / "build"

        if library_path is None:
            if os.name == "nt":
                # On Windows, try DLL first, then SO
                candidates = [
                    build_dir / "libscanmatch.dll",
                    build_dir / "scanmatch.dll",
                    build_dir / "libscanmatch.so",
                ]
            else:
                # On Linux / DigitalOcean, authoritative ELF library
                candidates = [
                    build_dir / "libscanmatch.so",
                    root_dir / "libscanmatch.so",
                    build_dir / "libscanmatch.dll",
                ]

            for cand in candidates:
                if cand.exists():
                    library_path = cand
                    break

            if library_path is None:
                # Default path for clear error reporting
                target_name = "libscanmatch.dll" if os.name == "nt" else "libscanmatch.so"
                library_path = build_dir / target_name

        lib_file = Path(library_path).resolve()
        if not lib_file.exists():
            raise ScanMatchError(
                f"ScanMatch library not found at: {lib_file}",
                code="LIBRARY_NOT_FOUND"
            )

        # On Windows, register directory for dependent DLL lookup if needed
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(lib_file.parent))
            except Exception:
                pass

        try:
            self.lib = ctypes.CDLL(str(lib_file))
        except Exception as e:
            raise ScanMatchError(
                f"Failed to load ScanMatch library ({lib_file.name}): {e}",
                code="LIBRARY_LOAD_ERROR"
            )

        # Declare C function signatures matching scanmatch_ffi.h
        self._setup_signatures()

        # Create persistent C context
        self.ctx = self.lib.sm_create_context()
        if not self.ctx:
            raise ScanMatchError("Failed to initialize ScanMatch context in C engine.", code="CONTEXT_INIT_FAILED")

    def _setup_signatures(self) -> None:
        """Configures argument and return types for ctypes calls."""
        # SM_Context *sm_create_context(void);
        self.lib.sm_create_context.argtypes = []
        self.lib.sm_create_context.restype = ctypes.c_void_p

        # void sm_destroy_context(SM_Context *ctx);
        self.lib.sm_destroy_context.argtypes = [ctypes.c_void_p]
        self.lib.sm_destroy_context.restype = None

        # int sm_load_catalog_csv_ffi(SM_Context *ctx, const char *path);
        self.lib.sm_load_catalog_csv_ffi.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.lib.sm_load_catalog_csv_ffi.restype = ctypes.c_int

        # int sm_process_text_json(SM_Context *ctx, const char *text, char **out_json);
        self.lib.sm_process_text_json.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_char_p)
        ]
        self.lib.sm_process_text_json.restype = ctypes.c_int

        # const char *sm_last_error(SM_Context *ctx);
        self.lib.sm_last_error.argtypes = [ctypes.c_void_p]
        self.lib.sm_last_error.restype = ctypes.c_char_p

        # void sm_free_string(char *s);
        self.lib.sm_free_string.argtypes = [ctypes.c_void_p]
        self.lib.sm_free_string.restype = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        """Frees the ScanMatch C context."""
        if getattr(self, "ctx", None):
            self.lib.sm_destroy_context(self.ctx)
            self.ctx = None

    def load_catalog(self, catalog_path: os.PathLike) -> None:
        """Loads product catalog CSV into the ScanMatch context."""
        cat_file = Path(catalog_path).resolve()
        if not cat_file.exists():
            raise ScanMatchError(f"Catalog file not found: {cat_file}", code="CATALOG_NOT_FOUND")

        rc = self.lib.sm_load_catalog_csv_ffi(self.ctx, str(cat_file).encode('utf-8'))
        if rc != 0:
            err_msg = self._get_last_error() or f"Error code {rc}"
            raise ScanMatchError(f"Catalog loading failed: {err_msg}", code="CATALOG_LOAD_FAILED")

    def process_text(self, ocr_text: str) -> Dict[str, Any]:
        """Sends extracted OCR text to libscanmatch C library for matching and parsing."""
        if not self.ctx:
            raise ScanMatchError("ScanMatch context is closed.", code="CONTEXT_CLOSED")

        # Encode input text to UTF-8 bytes for C library
        text_bytes = (ocr_text or "").encode('utf-8')
        out_ptr = ctypes.c_char_p()

        rc = self.lib.sm_process_text_json(self.ctx, text_bytes, ctypes.byref(out_ptr))
        if rc != 0:
            err_msg = self._get_last_error() or f"Return code {rc}"
            raise ScanMatchError(f"C matching engine failed: {err_msg}", code="C_MATCH_FAILED")

        try:
            if not out_ptr.value:
                return {
                    "success": False,
                    "error": {"code": "EMPTY_C_OUTPUT", "message": "No output returned from C library"},
                    "items": []
                }
            raw_json = out_ptr.value.decode('utf-8', errors='replace')
            try:
                return json.loads(raw_json)
            except json.JSONDecodeError as jde:
                raise ScanMatchError(f"Invalid JSON returned from C library: {jde}", code="INVALID_C_JSON")
        finally:
            if out_ptr:
                # Guarantee freeing C allocated string buffer
                self.lib.sm_free_string(ctypes.cast(out_ptr, ctypes.c_void_p))

    def _get_last_error(self) -> Optional[str]:
        """Retrieves last error message recorded by the C engine."""
        if not self.ctx:
            return None
        err = self.lib.sm_last_error(self.ctx)
        if err:
            return err.decode('utf-8', errors='replace')
        return None
