import os
import re
import sys
from pathlib import Path
import gradio as gr
from dotenv import load_dotenv
from crewai.project import load_crew

# Force UTF-8 encoding for stdout and stderr on Windows to prevent Emoji/Unicode encoding crashes
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Load environment variables from .env
load_dotenv()

def extract_urls(text):
    """
    Extracts URLs and titles from the research text.
    Handles both markdown format [Title](URL) and plain URLs.
    """
    if not text:
        return []
    
    # Regex to find markdown links: [text](url)
    markdown_links = re.findall(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', text)
    # Regex to find plain URLs that are not part of markdown links
    plain_urls = re.findall(r'(?<!\()(https?://[^\s)]+)', text)
    
    urls = []
    seen = set()
    
    # Process markdown links first
    for title, url in markdown_links:
        url = url.strip().rstrip('.,;)')
        if url not in seen:
            urls.append((title.strip(), url))
            seen.add(url)
            
    # Process plain URLs
    for url in plain_urls:
        url = url.strip().rstrip('.,;)')
        if url not in seen:
            # Fallback title as domain name
            domain = url.split('/')[2] if len(url.split('/')) > 2 else url
            urls.append((domain, url))
            seen.add(url)
            
    return urls

def run_research(topic: str):
    """
    Runs the CrewAI agent crew with the given topic, 
    then processes outputs to extract sources and the summary.
    """
    if not topic.strip():
        return (
            "### Please enter a search topic above.", 
            "<p style='color: #ef4444;'>No topic provided.</p>", 
            "No logs available."
        )
    
    # Check for credentials
    if not os.environ.get("OPENAI_API_KEY"):
        return (
            "### API Key Missing\n\nPlease add your `OPENAI_API_KEY` to the `.env` file.",
            "<p style='color: #ef4444;'>Missing OpenAI API Key</p>",
            "Error: OPENAI_API_KEY environment variable is not set."
        )
        
    if not os.environ.get("SERPER_API_KEY"):
        return (
            "### API Key Missing\n\nPlease add your `SERPER_API_KEY` to the `.env` file.",
            "<p style='color: #ef4444;'>Missing Serper API Key</p>",
            "Error: SERPER_API_KEY environment variable is not set."
        )
        
    try:
        # Load the crew from crew.jsonc
        crew_config_path = Path(__file__).parent / "crew.jsonc"
        crew, default_inputs = load_crew(crew_config_path)
        
        # Combine default inputs with the user topic
        inputs = {**default_inputs, "topic": topic}
        
        # Kick off the crew execution
        result = crew.kickoff(inputs=inputs)
        
        # The final summary is the main output of the crew
        summary = getattr(result, 'raw', str(result))
        
        # The web research specialist's task is the first task
        research_log = ""
        sources_html = "<p>No sources found.</p>"
        
        if hasattr(result, 'tasks_output') and len(result.tasks_output) > 0:
            # Get the output from the search specialist
            research_log = result.tasks_output[0].raw
            
            # Extract links from the research log
            urls = extract_urls(research_log)
            if urls:
                sources_html = "<div style='display: flex; flex-direction: column; gap: 10px; max-width: 1000px; margin: 0 auto;'>"
                for title, url in urls:
                    sources_html += f"""
                    <div style='background: rgba(255, 255, 255, 0.05); padding: 12px 18px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08); display: flex; align-items: center; justify-content: space-between;'>
                        <span style='font-weight: 600; color: #f3f4f6; max-width: 75%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'>📄 {title}</span>
                        <a href='{url}' target='_blank' style='background: linear-gradient(90deg, #3b82f6, #2563eb); color: white; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 0.85rem; font-weight: 500; transition: transform 0.2s;'>Visit Source</a>
                    </div>
                    """
                sources_html += "</div>"
            else:
                # Fallback: try extracting from final summary
                urls_from_summary = extract_urls(summary)
                if urls_from_summary:
                    sources_html = "<div style='display: flex; flex-direction: column; gap: 10px; max-width: 1000px; margin: 0 auto;'>"
                    for title, url in urls_from_summary:
                        sources_html += f"""
                        <div style='background: rgba(255, 255, 255, 0.05); padding: 12px 18px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08); display: flex; align-items: center; justify-content: space-between;'>
                            <span style='font-weight: 600; color: #f3f4f6; max-width: 75%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'>📄 {title}</span>
                            <a href='{url}' target='_blank' style='background: linear-gradient(90deg, #3b82f6, #2563eb); color: white; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 0.85rem; font-weight: 500; transition: transform 0.2s;'>Visit Source</a>
                        </div>
                        """
                    sources_html += "</div>"
                else:
                    sources_html = "<p style='color: #94a3b8; text-align: center;'>No source links could be parsed from the research.</p>"
        else:
            research_log = "No intermediate task outputs were generated."
            sources_html = "<p style='color: #94a3b8; text-align: center;'>No sources available.</p>"
            
        return summary, sources_html, research_log
        
    except Exception as e:
        error_msg = f"### Run Failed\n\nAn error occurred while executing the agent crew:\n\n```text\n{str(e)}\n```"
        return error_msg, "<p style='color: #ef4444;'>Execution failed.</p>", f"Error details:\n{str(e)}"

# Custom premium styling
custom_css = """
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

/* Main Container: Full Width & Symmetric Padding */
.gradio-container {
    font-family: 'Outfit', sans-serif !important;
    max-width: 100% !important;
    padding-left: 4% !important;
    padding-right: 4% !important;
    box-sizing: border-box !important;
}

#header-container {
    text-align: center;
    margin-bottom: 2rem;
    padding: 2.5rem 1rem;
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%);
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
}

#header-title {
    background: linear-gradient(90deg, #60a5fa, #3b82f6, #8b5cf6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 2.6rem !important;
    font-weight: 700 !important;
    margin-bottom: 0.5rem;
}

#header-desc {
    color: #94a3b8;
    font-size: 1.1rem;
}

/* Symmetric Align-items for row to align input box and button perfectly */
#input-row {
    align-items: flex-end !important;
    margin-bottom: 2rem !important;
    gap: 16px !important;
}

.gr-button-primary {
    background: linear-gradient(90deg, #3b82f6, #8b5cf6) !important;
    border: none !important;
    color: white !important;
    font-weight: 600 !important;
    transition: all 0.3s ease !important;
    box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3) !important;
}

.gr-button-primary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(59, 130, 246, 0.45) !important;
}

#launch-btn {
    height: var(--button-large-height, 42px) !important;
    margin-bottom: 0px !important;
}

.gr-box {
    border-radius: 12px !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
}

.gr-tab-button-active {
    border-bottom: 2px solid #3b82f6 !important;
    color: #3b82f6 !important;
    font-weight: 600 !important;
}

/* Scrollable, styled terminal-like research logs */
#research-log-textbox textarea {
    max-height: 500px !important;
    overflow-y: auto !important;
    font-family: 'Courier New', Courier, monospace !important;
    font-size: 0.95rem !important;
    background-color: #0f172a !important;
    color: #38bdf8 !important;
    border: 1px solid rgba(56, 189, 248, 0.2) !important;
    line-height: 1.6 !important;
    padding: 16px !important;
    box-sizing: border-box !important;
}
"""

with gr.Blocks() as demo:
    with gr.Column(elem_id="header-container"):
        gr.Markdown("# 🌐 Web Research & Summarizer", elem_id="header-title")
        gr.Markdown(
            "An AI-powered agent crew that automates web research, filters relevant topics, "
            "and transforms findings into structured Markdown summaries.",
            elem_id="header-desc"
        )
        
    with gr.Row(equal_height=True, elem_id="input-row"):
        topic_input = gr.Textbox(
            label="Enter Research Topic", 
            placeholder="e.g., Advancements in Quantum Computing in 2026",
            lines=1,
            scale=4
        )
        run_btn = gr.Button("Launch Agents", variant="primary", scale=1, elem_id="launch-btn")
            
    with gr.Row():
        with gr.Column():
            with gr.Tabs():
                with gr.Tab("📝 Summary"):
                    output_summary = gr.Markdown(value="### Your summary will be displayed here.")
                
                with gr.Tab("🔗 Extracted Sources"):
                    output_sources = gr.HTML(value="<p style='color: #94a3b8; text-align: center;'>Sources will appear here once scraped.</p>")
                    
                with gr.Tab("📋 Research Logs"):
                    output_log = gr.Textbox(
                        label="Search Specialist Output Logs", 
                        value="No logs available.", 
                        interactive=False,
                        lines=15,
                        elem_id="research-log-textbox"
                    )

    # Event handlers
    run_btn.click(
        fn=run_research,
        inputs=[topic_input],
        outputs=[output_summary, output_sources, output_log]
    )
    topic_input.submit(
        fn=run_research,
        inputs=[topic_input],
        outputs=[output_summary, output_sources, output_log]
    )

if __name__ == "__main__":
    # In Gradio 6.0+, theme and css must be passed in launch()
    demo.launch(
        server_name="127.0.0.1", 
        server_port=7860, 
        share=False,
        theme=gr.themes.Soft(primary_hue="blue", neutral_hue="slate"),
        css=custom_css
    )
