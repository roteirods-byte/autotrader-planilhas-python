from sheets_client import get_moedas, append_log

def run():
    append_log("JOB INICIADO")
    try:
        moedas = get_moedas()
        append_log(f"MOEDAS OK: {len(moedas)} lidas")
        print("MOEDAS (10):", moedas[:10])
    except Exception as e:
        append_log(f"JOB ERRO: {e}")

if __name__ == "__main__":
    run()
