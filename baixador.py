import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, ttk
import yt_dlp
from yt_dlp.utils import DownloadError
import os
import threading
import re
import sys
import io
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# --- FIX DE CONSOLE ---
if sys.stdout is None: sys.stdout = io.StringIO()
if sys.stderr is None: sys.stderr = io.StringIO()

# --- Globais ---
input_resultado = [None]
input_evento = threading.Event()
stop_requested = False 

# --- Temas ---
TEMAS = {
    'claro': {'bg': '#f0f0f0', 'fg': 'black', 'entry_bg': 'white', 'btn_fg': 'white', 'status': '#666'},
    'escuro': {'bg': '#1e1e1e', 'fg': 'white', 'entry_bg': '#333', 'btn_fg': 'white', 'status': '#ccc'}
}
tema_atual = 'escuro'

# --- Utils ---
def sanitize_filename(filename):
    return re.sub(r'[^\w\s-]', ' ', str(filename)).strip()

def get_smart_url(url):
    """
    A INTELIGÊNCIA DA V18:
    - Se for Playlist Normal (PL, UU): Transforma em link de playlist puro (mais estável).
    - Se for Mix (RD, TL): MANTÉM o link original (com v=), senão o YouTube bloqueia.
    """
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        if 'list' in params:
            list_id = params['list'][0]
            
            # SE FOR MIX (RD) ou QUEUE (TL), NÃO MEXE! (Precisa do vídeo context)
            if list_id.startswith(('RD', 'TL', 'OL')): # OL = Album topic as vezes precisa tb
                # Só removemos o index pra não travar num video especifico da fila
                if 'index' in params: params.pop('index', None)
                if 'start_radio' in params: params.pop('start_radio', None)
                
                # Reconstrói mantendo o v=
                new_query = urlencode(params, doseq=True)
                return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', new_query, ''))
            
            # SE FOR PLAYLIST PADRÃO, LIMPA TUDO (Deixa só a lista)
            else:
                new_query = urlencode({'list': list_id})
                return urlunparse((parsed.scheme, parsed.netloc, '/playlist', '', new_query, ''))
                
    except:
        pass
    return url # Se der erro, usa a original

def get_list_id(url):
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if 'list' in params: return params['list'][0]
    except: pass
    return None

# --- GUI Thread Safe ---
def executar_na_main(funcao_ui):
    input_resultado[0] = None
    input_evento.clear()
    def _wrapper():
        input_resultado[0] = funcao_ui()
        input_evento.set()
    root.after(0, _wrapper)
    input_evento.wait()
    return input_resultado[0]

def decidir_caminho_playlist(base_folder):
    criar_nova = messagebox.askyesno(
        "Destino", "Criar NOVA PASTA para essa playlist?\n\n👍 Sim = Nova Pasta\n👎 Não = Selecionar Pasta Existente",
        parent=root
    )
    if criar_nova:
        nome = simpledialog.askstring("Nova Pasta", "Nome da pasta:", parent=root)
        if not nome: nome = "Playlist_Sem_Nome"
        nome = sanitize_filename(nome)
        caminho = os.path.join(base_folder, nome)
    else:
        messagebox.showinfo("Selecione", "Escolha a pasta na próxima janela.", parent=root)
        caminho = filedialog.askdirectory(parent=root, title="Selecione onde salvar")
        if not caminho: caminho = os.path.join(base_folder, "Cancelados")
    return caminho

# --- Ações ---
def alternar_tema():
    global tema_atual
    tema_atual = 'escuro' if tema_atual == 'claro' else 'claro'
    c = TEMAS[tema_atual]
    root.config(bg=c['bg'])
    label_titulo.config(bg=c['bg'], fg=c['fg'])
    frame_top.config(bg=c['bg'])
    frame_input.config(bg=c['bg'])
    label_url.config(bg=c['bg'], fg=c['fg'])
    entry_url.config(bg=c['entry_bg'], fg=c['fg'], insertbackground=c['fg'])
    frame_opcoes.config(bg=c['bg'])
    rad_vid.config(bg=c['bg'], fg=c['fg'], selectcolor=c['bg'], activebackground=c['bg'], activeforeground=c['fg'])
    rad_aud.config(bg=c['bg'], fg=c['fg'], selectcolor=c['bg'], activebackground=c['bg'], activeforeground=c['fg'])
    status_label.config(bg=c['bg'], fg=c['status'])
    btn_tema.config(text="🌙 Escuro" if tema_atual == 'claro' else "☀ Claro")

def resetar_app():
    global stop_requested
    stop_requested = False
    progress_bar.stop()
    progress_bar.config(mode='determinate')
    entry_url.delete(0, tk.END)
    progress_bar['value'] = 0
    status_label.config(text="Pronto.")
    btn_baixar.config(state=tk.NORMAL, text="BAIXAR AGORA", bg="#2196F3")
    btn_cancelar.config(state=tk.DISABLED, bg="#cccccc", text="CANCELAR")

def solicitar_cancelamento():
    global stop_requested
    if messagebox.askyesno("Parar", "Deseja interromper o download?", parent=root):
        stop_requested = True
        btn_cancelar.config(text="PARANDO...", state=tk.DISABLED)
        status_label.config(text="🛑 Solicitando parada forçada...")

def iniciar_download():
    url = entry_url.get()
    if not url:
        messagebox.showwarning("Vazio", "Cola o link aí!", parent=root)
        return
    
    global stop_requested
    stop_requested = False
    
    btn_baixar.config(state=tk.DISABLED, text="RODANDO...")
    btn_cancelar.config(state=tk.NORMAL, bg="#f44336", text="CANCELAR")
    
    progress_bar.config(mode='indeterminate')
    progress_bar.start(10)
    
    t = threading.Thread(target=processar_download, args=(url,))
    t.start()

def processar_download(url_original):
    try:
        tipo = var_tipo.get()
        base_folder = "Downloads_Youtube"
        
        if not os.path.exists(base_folder):
            try: os.makedirs(base_folder)
            except: pass

        # 1. TRATAMENTO INTELIGENTE DA URL
        url_analise = get_smart_url(url_original)
        list_id = get_list_id(url_analise)

        # 2. Configurações Inteligentes
        ydl_opts_info = {
            'quiet': True, 'ignoreerrors': True, 'no_warnings': True, 'logger': None
        }

        # Identifica tipo
        eh_playlist_padrao = list_id and list_id.startswith(('PL', 'UU', 'FL', 'LP'))
        eh_mix = list_id and list_id.startswith(('RD', 'TL'))

        if eh_playlist_padrao:
            root.after(0, lambda: status_label.configure(text="🚀 Playlist Normal: Modo Turbo..."))
            ydl_opts_info['extract_flat'] = True
        elif eh_mix:
            root.after(0, lambda: status_label.configure(text="🎵 Mix Infinito: Analisando amostra..."))
            ydl_opts_info['extract_flat'] = False 
            ydl_opts_info['playlistend'] = 25 # Limite de segurança
        else:
            root.after(0, lambda: status_label.configure(text="🔎 Analisando link..."))
            ydl_opts_info['extract_flat'] = True

        # 3. Extração
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info_dict = ydl.extract_info(url_analise, download=False)

        root.after(0, lambda: progress_bar.stop())
        root.after(0, lambda: progress_bar.config(mode='determinate'))
        root.after(0, lambda: progress_bar.configure(value=0))

        lista_videos = []
        is_playlist_mode = False

        if 'entries' in info_dict:
            lista_videos = list(info_dict['entries'])
            lista_videos = [v for v in lista_videos if v is not None]
            qtd = len(lista_videos)
            
            root.after(0, lambda: status_label.configure(text=f"✅ Achamos {qtd} vídeos!"))

            def perguntar_modo():
                return messagebox.askyesno(
                    "Playlist Detectada", 
                    f"Encontrei {qtd} vídeos!\n\nSim = Baixar TUDO\nNão = Baixar SÓ O PRIMEIRO",
                    parent=root
                )
            
            if qtd > 0:
                is_playlist_mode = executar_na_main(perguntar_modo)
                if not is_playlist_mode:
                    # Se negou a lista, tenta pegar o vídeo que estava na URL original
                    # Para mixes, o primeiro da lista geralmente é o vídeo atual
                    lista_videos = [lista_videos[0]]
            else:
                lista_videos = [info_dict]
        else:
            lista_videos = [info_dict]

        # 4. Pasta
        path_final = ""
        if is_playlist_mode:
            path_final = executar_na_main(lambda: decidir_caminho_playlist(os.path.abspath(base_folder)))
        else:
            path_final = os.path.join(base_folder, "Arquivos_Soltos")
        
        if not os.path.exists(path_final): os.makedirs(path_final)

        # 5. Download
        total_items = len(lista_videos)
        root.after(0, lambda: status_label.configure(text=f"🚀 Iniciando fila de {total_items} vídeos..."))
        
        for i, video in enumerate(lista_videos):
            if stop_requested: break

            try:
                video_url = video.get('url') or video.get('webpage_url')
                if not video_url and video.get('id'): 
                    video_url = f"https://www.youtube.com/watch?v={video.get('id')}"
                
                if not video_url: continue

                titulo = video.get('title', f'Video {i+1}')
                texto_status = f"[{i+1}/{total_items}] Baixando: {str(titulo)[:30]}..."
                root.after(0, lambda t=texto_status: status_label.configure(text=t))

                def progress_hook(d):
                    if stop_requested:
                        raise DownloadError("Cancelado pelo usuário")
                    
                    if d['status'] == 'downloading':
                        try:
                            total = d.get('total_bytes') or d.get('total_bytes_estimate')
                            baixado = d.get('downloaded_bytes', 0)
                            if total:
                                p = (baixado / total) * 100
                                root.after(0, lambda: progress_bar.configure(value=p))
                        except: pass
                
                ydl_opts_down = {
                    'outtmpl': f'{path_final}/%(title)s.%(ext)s',
                    'restrictfilenames': True, 'ignoreerrors': True, 'quiet': True, 'no_warnings': True,
                    'progress_hooks': [progress_hook],
                    'ffmpeg_location': r'C:\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe'
                }

                if tipo == 'audio':
                    ydl_opts_down.update({
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                    })
                else:
                    ydl_opts_down.update({'format': 'bv*+ba/best', 'merge_output_format': 'mp4', 'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]})

                with yt_dlp.YoutubeDL(ydl_opts_down) as ydl:
                    ydl.download([video_url])
            
            except (DownloadError, Exception) as e:
                if "Cancelado" in str(e) or stop_requested:
                    root.after(0, lambda: status_label.configure(text="🛑 Parando fila..."))
                    break
                print(f"Erro item {i}: {e}")
                continue

        if stop_requested:
            root.after(0, lambda: status_label.configure(text="🛑 Cancelado."))
            root.after(0, lambda: messagebox.showinfo("Aviso", "Download interrompido!", parent=root))
        else:
            root.after(0, lambda: status_label.configure(text="✅ Finalizado!"))
            root.after(0, lambda: messagebox.showinfo("Sucesso", f"Salvo em:\n{path_final}", parent=root))
        
        root.after(1500, lambda: resetar_app())

    except Exception as e:
        root.after(0, lambda: status_label.configure(text="❌ Erro Fatal."))
        root.after(0, lambda: messagebox.showerror("Erro", str(e), parent=root))
        root.after(0, lambda: resetar_app())

# --- UI ---
root = tk.Tk()
root.title("YT-Downloader - Inteligência Mix/Playlist - by: Liandro")
root.geometry("600x530")

frame_top = tk.Frame(root)
frame_top.pack(fill=tk.X, padx=10, pady=5)
btn_tema = tk.Button(frame_top, text="🌙 Modo Escuro", command=alternar_tema, font=("Arial", 8))
btn_tema.pack(side=tk.LEFT)
btn_reset = tk.Button(frame_top, text="🔄 Resetar", command=resetar_app, font=("Arial", 8), bg="#FF9800", fg="white")
btn_reset.pack(side=tk.RIGHT)

label_titulo = tk.Label(root, text="YouTube Downloader Pro\nBy: Liandro Chaves", font=("Segoe UI", 16, "bold"))
label_titulo.pack(pady=10)

frame_input = tk.Frame(root)
frame_input.pack(pady=5)
label_url = tk.Label(frame_input, text="URL:", font=("Arial", 10))
label_url.pack(side=tk.LEFT, padx=5)
entry_url = tk.Entry(frame_input, width=50, font=("Arial", 11))
entry_url.pack(side=tk.LEFT)

var_tipo = tk.StringVar(value="video")
frame_opcoes = tk.Frame(root)
frame_opcoes.pack(pady=10)
rad_vid = tk.Radiobutton(frame_opcoes, text="Vídeo MP4", variable=var_tipo, value="video", font=("Arial", 10))
rad_vid.pack(side=tk.LEFT, padx=15)
rad_aud = tk.Radiobutton(frame_opcoes, text="Áudio MP3", variable=var_tipo, value="audio", font=("Arial", 10))
rad_aud.pack(side=tk.LEFT, padx=15)

frame_acao = tk.Frame(root)
frame_acao.pack(pady=10)
btn_baixar = tk.Button(frame_acao, text="BAIXAR AGORA", bg="#2196F3", fg="white", font=("Segoe UI", 11, "bold"), padx=20, pady=8, command=iniciar_download)
btn_baixar.pack(side=tk.LEFT, padx=5)
btn_cancelar = tk.Button(frame_acao, text="CANCELAR", bg="#cccccc", fg="white", font=("Segoe UI", 10, "bold"), padx=10, pady=8, command=solicitar_cancelamento, state=tk.DISABLED)
btn_cancelar.pack(side=tk.LEFT, padx=5)

progress_bar = ttk.Progressbar(root, orient="horizontal", length=500, mode="determinate")
progress_bar.pack(pady=15)

status_label = tk.Label(root, text="Pronto.", font=("Consolas", 9), fg="#666")
status_label.pack(side=tk.BOTTOM, pady=15)

alternar_tema(); alternar_tema()
root.mainloop()