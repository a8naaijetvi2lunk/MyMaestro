"""Faux serveur HTTP local de fichiers pour tester les téléchargements : gère `Range`, coupures, 404, contenu corrompu."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FauxServeurFichiers:
    """Sert `contenu` sur `/fichier.bin`. Les options se règlent sur l'instance avant ou pendant les requêtes."""

    def __init__(self, contenu: bytes) -> None:
        self.contenu = contenu
        self.couper_apres: int | None = None  # coupe la connexion après N octets de corps (une seule fois par option posée)
        self.se_taire_apres: int | None = None  # envoie N octets de corps puis se tait (connexion ouverte) jusqu'à la sortie
        self._liberer = threading.Event()
        self.ignorer_range = False  # répond 200 avec le fichier entier, même si Range est demandé
        self.corrompu = False  # sert des octets de même longueur mais différents
        self.repondre_404 = False
        self.requetes: list[dict[str, str | None]] = []  # une entrée par requête : {"range": ...}
        serveur = self

        class Gestionnaire(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # silence
                pass

            def do_GET(self) -> None:
                serveur.requetes.append({"range": self.headers.get("Range")})
                if serveur.repondre_404:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                donnees = bytes(b ^ 0xFF for b in serveur.contenu) if serveur.corrompu else serveur.contenu
                total = len(donnees)
                debut = 0
                demande = self.headers.get("Range")
                partiel = False
                if demande and not serveur.ignorer_range and demande.startswith("bytes="):
                    debut = int(demande[len("bytes=") :].split("-")[0])
                    partiel = True
                corps = donnees[debut:]
                if partiel:
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {debut}-{total - 1}/{total}")
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                silence = serveur.se_taire_apres
                if silence is not None:
                    try:
                        self.wfile.write(corps[:silence])
                        self.wfile.flush()
                    except OSError:
                        return
                    serveur._liberer.wait(30)
                    self.close_connection = True
                    return
                limite = serveur.couper_apres
                if limite is not None:
                    serveur.couper_apres = None
                    self.wfile.write(corps[:limite])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                try:
                    self.wfile.write(corps)
                except OSError:
                    pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self._httpd.daemon_threads = True
        self._fil = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}/fichier.bin"

    def __enter__(self) -> "FauxServeurFichiers":
        self._fil.start()
        return self

    def __exit__(self, *args) -> None:
        self._liberer.set()
        self._httpd.shutdown()
        self._httpd.server_close()
