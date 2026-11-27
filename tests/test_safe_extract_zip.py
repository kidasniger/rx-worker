#!/usr/bin/env python3
"""Tests de l'extraction ZIP défensive (scripts/safe_extract_zip.py).

Exécutés sans dépendance externe : python3 -m unittest discover -s tests -v
Chaque attaque connue (zip-slip, chemin absolu, lien symbolique, doublon,
bombe, fichier spécial, caractère de contrôle) doit être refusée, et le
dossier de destination nettoyé après échec.
"""
import io
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from safe_extract_zip import UnsafeArchive, extract_archive, safe_relative_path  # noqa: E402


def make_zip(entries):
    """Construit une archive en mémoire : {nom: (contenu, attr_externe)}."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, (content, attr) in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = attr
            bundle.writestr(info, content)
    return buffer.getvalue()


REG = 0o644 << 16
DIR = (0o755 << 16) | 0x10


class TestChemins(unittest.TestCase):
    def test_chemins_refuses(self):
        for raw in ["../evil.txt", "/absolu.txt", "C:\\windows\\x", "a/../../x",
                    "a//b", "", "a\x00b", "a\nb", "."]:
            with self.assertRaises(UnsafeArchive, msg=repr(raw)):
                safe_relative_path(raw)

    def test_chemins_valides(self):
        path, is_dir = safe_relative_path("a/./b/c.html")
        self.assertEqual(path.as_posix(), "a/b/c.html")
        self.assertFalse(is_dir)
        path, is_dir = safe_relative_path("dossier/")
        self.assertTrue(is_dir)


class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rdx-zip-test-")
        self.archive = Path(self.tmp) / "archive.zip"
        self.dest = Path(self.tmp) / "dest"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, entries):
        self.archive.write_bytes(make_zip(entries))

    def test_archive_valide(self):
        self._write({
            "index.html": (b"<html>ok</html>", REG),
            "assets/style.css": (b"body{}", REG),
            "dossier/": (b"", DIR),
        })
        main_file = extract_archive(self.archive, self.dest, "index.html")
        self.assertTrue(Path(main_file).is_file())
        self.assertEqual(Path(main_file).read_bytes(), b"<html>ok</html>")
        self.assertEqual((self.dest / "assets/style.css").read_bytes(), b"body{}")

    def test_zip_slip_refuse(self):
        self._write({"../evil.txt": (b"x", REG)})
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "index.html")
        self.assertFalse((Path(self.tmp) / "evil.txt").exists())
        self.assertFalse(self.dest.exists())  # nettoyage après échec

    def test_chemin_absolu_refuse(self):
        self._write({"/etc/passwd": (b"x", REG)})
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "/etc/passwd")

    def test_lien_symbolique_refuse(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            info = zipfile.ZipInfo("lien.html")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, "cible.html")
        self.archive.write_bytes(buffer.getvalue())
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "lien.html")

    def test_fichier_special_refuse(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            info = zipfile.ZipInfo("fifo")
            info.external_attr = (stat.S_IFIFO | 0o644) << 16
            bundle.writestr(info, "")
        self.archive.write_bytes(buffer.getvalue())
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "fifo")

    def test_doublon_refuse(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as dst:
            dst.writestr("a.html", b"1")
            info = zipfile.ZipInfo("a.html")
            info.external_attr = REG
            dst.writestr(info, b"2")
        self.archive.write_bytes(buffer.getvalue())
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "a.html")

    def test_bombe_par_taille_declaree_refusee(self):
        # 101 Mo de zéros : taille déclarée > MAX_FILE_BYTES (100 Mo),
        # refusée AVANT toute écriture. Compression ~1000:1 : archive légère.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            bundle.writestr("gros.html", b"\0" * (101 * 1000 * 1000))
        self.archive.write_bytes(buffer.getvalue())
        self.assertLess(self.archive.stat().st_size, 2 * 1000 * 1000)
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "gros.html")
        self.assertFalse(self.dest.exists())

    def test_trop_d_entrees_refuse(self):
        entries = {f"f{i}.txt": (b"x", REG) for i in range(2001)}
        self._write(entries)
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "index.html")

    def test_html_principal_absent_refuse(self):
        self._write({"autre.txt": (b"x", REG)})
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "index.html")

    def test_html_principal_doit_etre_html(self):
        self._write({"main.txt": (b"x", REG)})
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "main.txt")

    def test_dossier_non_vide_refuse(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            info = zipfile.ZipInfo("dossier/")
            info.external_attr = DIR
            bundle.writestr(info, b"contenu interdit")
        self.archive.write_bytes(buffer.getvalue())
        with self.assertRaises(UnsafeArchive):
            extract_archive(self.archive, self.dest, "index.html")

    def test_destination_reinitialisee(self):
        self.dest.mkdir()
        (self.dest / "ancien.txt").write_text("à supprimer")
        self._write({"index.html": (b"ok", REG)})
        extract_archive(self.archive, self.dest, "index.html")
        self.assertFalse((self.dest / "ancien.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
