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

if not "history_3" in st.session_state:
    st.session_state.history_3 = "{}"

if not "history_4" in st.session_state:
    st.session_state.history_4 = "{}"

def get_bot_response(user_input, pb):
    client = ConvaAI(
        assistant_id=st.secrets.conva_assistant_id,
        api_key=st.secrets.conva_api_key,
        assistant_version="17.0.0",
    )

    pb.progress(30, "Generating URLs for the query...")
    response = client.invoke_capability_name(
        query=user_input,
        history=st.session_state.history_1,
        capability_name="query_generation",
        timeout=600,
        stream=False,
    )

    # print("query_generation response: {}\n\n".format(response))

    st.session_state.history_1 = response.conversation_history

    urls = response.parameters.get("query_urls", [])

    if urls:
        pb.progress(50, "Scraping {} URLs for context... (this may take a while)".format(len(urls)))
        contents = asyncio.run(scrape_multiple(urls))

        context = ""
        for url, content in contents.items():
            context += "URL: {}\nContents: {}\n\n".format(url, content)

        full_context = context

        pb.progress(75, "Extracting and aggregating information from the context...")
        capability_context = {"data_aggregation": context.strip()}

        response = client.invoke_capability_name(
            query=user_input,
            capability_name="data_aggregation",
            history=st.session_state.history_2,
            timeout=600,
            stream=False,
            capability_context=capability_context,
        )
        # print("data_aggregation response: {}\n\n".format(response))
        st.session_state.history_2 = response.conversation_history

        if response.parameters.get("function") and response.parameters.get("values"):
            fn = response.parameters.get("function")
            values = response.parameters.get("values")
            tmp = {}
            for k, vals in values.items():
                tmp[k] = []
                if isinstance(vals, list):
                    for i, v in enumerate(vals):
                        try:
                            tmp[k].append(float(v))
                        except (Exception,):
                            tmp[k].append(0)
                else:
                    try:
                        tmp[k].append(float(vals))
                    except (Exception,):
                        tmp[k].append(0)
            ret = {}
            for key, value in tmp.items():
                if fn == "sum":
                    ret[key] = sum(value)
                elif fn == "average":
                    ret[key] = sum(value) / len(value)
                elif fn == "max":
                    ret[key] = max(value)
                elif fn == "min":
                    ret[key] = min(value)

            ctx = "The {} of the given values is: \n".format(fn)
            for key, value in ret.items():
                ctx += "{}: {}\n".format(key, value)

            ctx += context
            context = ctx

        pb.progress(80, "Generating the answer...")
        capability_context = {"data_analysis_and_visualization": context.strip()}
        response = client.invoke_capability_name(
            query=user_input,
            capability_name="data_analysis_and_visualization",
            history=st.session_state.history_3,
            timeout=600,
            stream=False,
            capability_context=capability_context,
        )

        # print("data_av response: {}\n\n".format(response))
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

        # print("data_v response: {}\n\n".format(response))
        st.session_state.history_4 = response.conversation_history

        graph_data = {
            "type": response.parameters.get("type"),
            "labels": response.parameters.get("labels"),
            "x": response.parameters.get("x_data"),
            "y": response.parameters.get("y_data"),
            "pie_values": response.parameters.get("pie_values"),
        }
        return text_response, graph_data, full_context
    return response.message, {}, ""

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
            fig.add_trace(go.Scatter(x=x_data, y=y, mode='lines+markers', name=name))
            fig.update_xaxes(type='category')
            fig.update_layout(
                title="",
                xaxis_title=labels[0],
                yaxis_title=labels[1],
                height=400  # Adjust the height as needed
            )

    elif type == "bar":
        for name, y in y_data.items():
            fig.add_trace(go.Bar(x=x_data, y=y, name=name))
            fig.update_xaxes(type='category')
            fig.update_layout(
                title="",
                xaxis_title=labels[0],
                yaxis_title=labels[1],
                height=400  # Adjust the height as needed
            )

    elif type == "pie":
        fig = go.Figure(data=[go.Pie(labels=labels, values=pie_values)])
        fig.update_layout(
            title="",
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
                    st.markdown(sources)

        # Add assistant response to chat history
        if graph_data.get("y"):
            st.session_state.messages.append({"role": "assistant", "content": response, "graph": fig})

if __name__ == "__main__":
    main()
