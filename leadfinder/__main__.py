import os

from waitress import serve

from leadfinder import create_app


def main():
    port = int(os.environ.get("LEADFINDER_PORT", "5000"))
    print(f"LeadFinder disponível em http://127.0.0.1:{port}", flush=True)
    serve(create_app(), host="127.0.0.1", port=port, threads=4)


if __name__ == "__main__":
    main()
