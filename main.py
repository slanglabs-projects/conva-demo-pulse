import asyncio
import os
from conva_ai import ConvaAI

from scraping import scrape_multiple

import streamlit as st
import plotly.graph_objects as go

# Hack to get playwright to work properly
os.system("playwright install")

if not "sources" in st.session_state:
    st.session_state.sources = []

if not "history_1" in st.session_state:
    st.session_state.history_1 = "{}"

if not "history_2" in st.session_state:
    st.session_state.history_2 = "{}"

def get_bot_response(user_input):
    client = ConvaAI(
        assistant_id=st.secrets.conva_assistant_id,
        api_key=st.secrets.conva_api_key,
        assistant_version="15.0.0",
    )

    st.write("Generating URLs for the query...")
    response = client.invoke_capability_name(
        query=user_input,
        history=st.session_state.history_1,
        capability_name="query_generation",
        timeout=600,
        stream=False,
    )

    st.session_state.history_1 = response.conversation_history

    urls = response.parameters.get("query_urls", [])

    if urls:
        st.write("Scraping the URLs for context...")
        st.write("This may take a while...")
        contents = asyncio.run(scrape_multiple(urls))

        context = ""
        for url, content in contents.items():
            context += "URL: {}\nContents: {}\n\n".format(url, content)

        print(context + "\n\n")

        st.write("Generating answer...")
        capability_context = {"data_analysis": context.strip()}

        response = client.invoke_capability_name(
            query=user_input,
            capability_name="data_analysis_and_visualization",
            history=st.session_state.history_2,
            timeout=600,
            stream=False,
            capability_context=capability_context,
        )

        st.session_state.history_2 = response.conversation_history

        text_response = response.message
        graph_data = response.parameters.get("graph_data", {})
        return text_response, graph_data

    return response.message, {}

def generate_graph(data):
    # Create a Plotly figure
    fig = go.Figure()
    x_data = data.get("x", [])
    y_data = data.get("y", {})
    labels = data.get("labels", ["x-axis", "y-axis"])

    for name, y in y_data.items():
        fig.add_trace(go.Scatter(x=x_data, y=y, mode='lines+markers', name=name))

    # fig = go.Figure(data=go.Scatter(x=data['x'], y=data['y'], mode='lines+markers'))
    fig.update_layout(
        title="Pulse Graph",
        xaxis_title=labels[0],
        yaxis_title=labels[1],
        height=400  # Adjust the height as needed
    )
    return fig

def main():
    st.title("PhonePe Pulse Q&A")

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "graph" in message:
                st.plotly_chart(message["graph"], use_container_width=True)

    # React to user input
    if prompt := st.chat_input("What would you like to know?"):
        # Display user message in chat message container
        st.chat_message("user").markdown(prompt)
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Get bot response (text and graph data)
        response, graph_data = get_bot_response(prompt)

        if not response:
            response = "Sorry, I couldn't find any information on that."

        # Display assistant response in chat message container
        with st.chat_message("assistant"):
            st.markdown(response)
            if graph_data.get("y"):
                fig = generate_graph(graph_data)
                st.plotly_chart(fig, use_container_width=True)

        # Add assistant response to chat history
        if graph_data.get("y"):
            st.session_state.messages.append({"role": "assistant", "content": response, "graph": fig})

if __name__ == "__main__":
    main()
