from gradio_client import Client

SPACE = "Qwen/Qwen3-VL-235B-A22B-Instruct-Demo"
client = Client(SPACE, verbose=False)
print(client.view_api(all_endpoints=True))
