import asyncio
import json
import os
from conva_ai import ConvaAI

from scraping import fetch_multiple

import streamlit as st
import plotly.graph_objects as go

DEBUG = False
URL_TEMPLATES = {
    "overview": "https://www.phonepe.com/pulsestatic/v1/explore-data/map/{}/hover/country/india",
    "detailed": "https://www.phonepe.com/pulsestatic/v1/explore-data/aggregated/{}/country/india",
    "top10": "https://www.phonepe.com/pulsestatic/v1/explore-data/top/{}/country/india",
}


# Hack to get playwright to work properly
os.system("playwright install")

if not "sources" in st.session_state:
    st.session_state.sources = []

if not "history_1" in st.session_state:
    st.session_state.history_1 = "{}"

if not "history_2" in st.session_state:
    st.session_state.history_2 = "{}"

if not "history_3" in st.session_state:
    st.session_state.history_3 = "{}"

if not "history_4" in st.session_state:
    st.session_state.history_4 = "{}"

if not "related" in st.session_state:
    st.session_state.related = []

if not "new_query" in st.session_state:
    st.session_state.new_query = None

if not "started" in st.session_state:
    st.session_state.started = False

if os.path.exists("related.json"):
    with open("related.json", "r") as f:
        st.session_state.related = json.load(f)


def make_api_calls(query, client, pb, history="{}"):
    pb.progress(30, "Understanding the query...")
    response = client.invoke_capability_name(
        query=query,
        capability_name="data_query_parsing",
        history=history,
        timeout=600,
        stream=False,
    )

    if DEBUG:
        print("data_query_parsing response: {}\n\n".format(response))

    query_type = response.parameters.get("query_type", "transaction")
    query_subtype = response.parameters.get("query_subtype", "overview")
    years = response.parameters.get("years", [])
    quarters = response.parameters.get("quarters", [])
    quarters = [quarter.replace("Q", "") if isinstance(quarter, str) else quarter for quarter in quarters]
    quarters = [quarter.replace("q", "") if isinstance(quarter, str) else quarter for quarter in quarters]
    quarters = ["1", "2", "3", "4"] if not quarters else quarters
    regions = response.parameters.get("regions", [])

    urls = []
    tmp_urls = []
    url_template = URL_TEMPLATES.get(query_subtype).format(query_type)
    for region in regions:
        if "city" in region and region["city"]:
            turl = url_template + "/state/{}".format(region.get("state").lower().replace(" ", "-"))
            if turl not in tmp_urls:
                tmp_urls.append(turl)

    if not tmp_urls:
        tmp_urls.append(url_template)

    for year in years:
        for quarter in quarters:
            for turl in tmp_urls:
                url = turl + "/{}/{}.json".format(year, quarter)
                urls.append(url)
    if DEBUG:
        print("URLs: {}\n\n".format(urls))

    if not urls:
        return {}, response.conversation_history

    pb.progress(50, "Making {} API calls... (this will take a while)".format(len(urls)))
    contents = asyncio.run(fetch_multiple(urls))

    if response.related_queries:
        st.session_state.related = response.related_queries
        # with open("related.json", "w") as f:
        # json.dump(st.session_state.related, f)

    return contents, response.conversation_history


def get_bot_response(user_input, pb):
    client = ConvaAI(
        assistant_id=st.secrets.conva_assistant_id,
        api_key=st.secrets.conva_api_key,
        assistant_version="30.0.0",
    )

    contents, history = make_api_calls(user_input, client, pb, st.session_state.history_1)
    full_context = contents

    if not contents:
        return contents, {}, full_context

    context = "\n".join(["{}\n{}\n{}\n\n".format(url, content, "-" * 50) for url, content in contents.items()])
    context = context.replace("{", "{{").replace("}", "}}")

    if DEBUG:
        print("context for data_summary = {}".format(context))

    st.session_state.history_1 = history

    pb.progress(80, "Generating the answer...")
    capability_context = {"data_summary": context.strip()}
    response = client.invoke_capability_name(
        query=user_input,
        capability_name="data_summary",
        history=st.session_state.history_3,
        timeout=600,
        stream=False,
        capability_context=capability_context,
    )

    if DEBUG:
        print("data_summary response: {}\n\n".format(response))

    st.session_state.history_3 = response.conversation_history
    text_response = response.message

    context = response.message
    pb.progress(90, "Generating the visualization...")
    capability_context = {"data_visualization": context.strip()}
    response = client.invoke_capability_name(
        query=user_input,
        capability_name="data_visualization",
        history=st.session_state.history_4,
        timeout=600,
        stream=False,
        capability_context=capability_context,
    )

    if DEBUG:
        print("data_visualization response: {}\n\n".format(response))
    st.session_state.history_4 = response.conversation_history

    pb.progress(100, "Done")

    graph_data = {
        "type": response.parameters.get("type"),
        "labels": response.parameters.get("labels"),
        "x": response.parameters.get("x_data"),
        "y": response.parameters.get("y_data"),
        "pie_values": response.parameters.get("pie_values"),
    }
    return text_response, graph_data, full_context


def generate_graph(data):
    # Create a Plotly figure
    fig = go.Figure()
    type = data.get("type", "line")
    labels = data.get("labels", ["x-axis", "y-axis"])
    x_data = data.get("x", [])
    y_data = data.get("y", {})
    pie_values = data.get("pie_values", [])

    if type == "line":
        for name, y in y_data.items():
            fig.add_trace(go.Scatter(x=x_data, y=y, mode="lines+markers", name=name))
            fig.update_xaxes(type="category")
            fig.update_layout(
                title="",
                xaxis_title=labels[0],
                yaxis_title=labels[1],
                height=400,  # Adjust the height as needed
            )

    elif type == "bar":
        for name, y in y_data.items():
            if x_data:
                fig.add_trace(go.Bar(x=x_data, y=y, name=name))
            elif labels:
                fig.add_trace(go.Bar(x=labels, y=y, name=name))
            fig.update_xaxes(type="category")
            fig.update_layout(
                title="",
                xaxis_title=labels[0],
                yaxis_title=labels[1],
                height=400,  # Adjust the height as needed
            )

    elif type == "pie":
        fig = go.Figure(data=[go.Pie(labels=labels, values=pie_values)])
        fig.update_layout(title="", height=400)  # Adjust the height as needed

    return fig


st.markdown(
    """
<style>
button * {
    height: auto;
}
button p {
    font-size: .8em;
}
</style>
""",
    unsafe_allow_html=True,
)


def handle_button_click(query):
    st.session_state.new_query = query
    if not st.session_state.started:
        st.session_state.started = True


def process_query(prompt):
    # Display user message in chat message container
    st.chat_message("user").markdown(prompt)
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        placeholder = st.empty()
        _, col1, _ = placeholder.columns([1, 3, 1])
        pb = col1.progress(0, "Understanding your query...")

        # Get bot response (text and graph data)
        response, graph_data, sources = get_bot_response(prompt, pb)

        if not response:
            response = "Sorry, I couldn't find any information on that."

        placeholder.empty()

        st.markdown(response)
        if graph_data.get("y") or graph_data.get("pie_values"):
            fig = generate_graph(graph_data)
            st.plotly_chart(fig, use_container_width=True)

        if sources:
            with st.expander("Sources"):
                for index, url in enumerate(sources.keys()):
                    st.markdown(
                        "{}. <a href='{}'>{}</a>".format(index + 1, url, url),
                        unsafe_allow_html=True,
                    )

    # Add assistant response to chat history
    if graph_data.get("y" or graph_data.get("pie_values")):
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": response,
                "graph": fig,
                "sources": sources,
            }
        )
    else:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": response,
            }
        )

    if st.session_state.related:
        related = sorted(st.session_state.related, key=lambda l: len(l))
        col1, col2, col3 = st.columns(3)
        l = len(related)
        if l > 0:
            col1.button(related[0], key="{}_1".format(related[0]), on_click=handle_button_click, args=[related[0]])
        if l > 1:
            col2.button(related[1], key="{}_2".format(related[1]), on_click=handle_button_click, args=[related[1]])
        if l > 2:
            col3.button(related[2], key="{}_3".format(related[2]), on_click=handle_button_click, args=[related[2]])


def main():
    st.title("PhonePe Pulse Q&A")
    st.divider()

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "graph" in message:
                st.plotly_chart(message["graph"], use_container_width=True)
            if "sources" in message:
                sources = message["sources"]
                with st.expander("Sources"):
                    for index, url in enumerate(sources.keys()):
                        st.markdown(
                            "{}. <a href='{}'>{}</a>".format(index + 1, url, url),
                            unsafe_allow_html=True,
                        )

    if not st.session_state.started:
        if st.session_state.related:
            related = sorted(st.session_state.related, key=lambda l: len(l))
            col1, col2, col3 = st.columns(3)
            l = len(related)
            if l > 0:
                col1.button(related[0], on_click=handle_button_click, args=[related[0]])
            if l > 1:
                col2.button(related[1], on_click=handle_button_click, args=[related[1]])
            if l > 2:
                col3.button(related[2], on_click=handle_button_click, args=[related[2]])

    if st.session_state.new_query:
        prompt = st.session_state.new_query
        st.session_state.new_query = None
        process_query(prompt)

    # React to user input
    if prompt := st.chat_input("What would you like to know?"):
        if not st.session_state.started:
            st.session_state.started = True
        process_query(prompt)


if __name__ == "__main__":
    main()
