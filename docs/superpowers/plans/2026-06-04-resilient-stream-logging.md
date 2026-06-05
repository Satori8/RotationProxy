# Resilient Stream Logging and Timeout Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix silent stream swallowing, implement detailed logging of atypical situations during data transmission, and optimize HTTPX timeouts and connection pooling to prevent freezes while supporting slow free keys with large contexts.

**Architecture:** 
- Propagate exceptions (`raise`) in `iter_bytes` to prevent FastAPI from silently closing connections with `200 OK` on network errors.
- Implement detailed logging of stream start, successful completion, client disconnects (`asyncio.CancelledError`), and network errors.
- Optimize `httpx.Timeout` with a generous `read=120.0` timeout to support slow free keys with large contexts, and set `keepalive_expiry=30.0` to prevent stale connections in the pool.

**Tech Stack:** Python, FastAPI, HTTPX, Asyncio

---

### Task 1: Optimize HTTPX Client Timeouts and Limits in `proxy_core/server.py`

**Files:**
- Modify: `proxy_core/server.py:597-620`

- [ ] **Step 1: Update lifespan client initialization**
  Modify the `lifespan` function to use a detailed `httpx.Timeout` with `read=120.0` and configure `keepalive_expiry=30.0` on `httpx.Limits`.

  *Code change preview:*
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      limits = httpx.Limits(
          max_keepalive_connections=100,
          max_connections=200,
          keepalive_expiry=30.0  # Close idle connections after 30s to prevent stale sockets
      )
      timeout = httpx.Timeout(
          connect=15.0,
          read=120.0,  # Generous 120s read timeout to support slow free keys with large contexts
          write=15.0,
          pool=15.0
      )

      # Initialize 7 clients: index 0 (unbound) + indexes 1-6 (bound to corresponding VPN local IPs)
      app.state.vpn_clients = {0: httpx.AsyncClient(timeout=timeout, limits=limits)}
      for i in range(1, 7):
          try:
              transport = httpx.AsyncHTTPTransport(local_address=f"10.8.0.1{i}")
              app.state.vpn_clients[i] = httpx.AsyncClient(
                  transport=transport, timeout=timeout, limits=limits
              )
              logger.info(
                  f"[Lifespan] Initialized bound HTTP client for VPN {i} (10.8.0.1{i})"
              )
          except Exception as e:
              logger.error(
                  f"[Lifespan] Failed to bind client to VPN IP 10.8.0.1{i} (falling back to unbound): {e}"
              )
              app.state.vpn_clients[i] = httpx.AsyncClient(timeout=timeout, limits=limits)
  ```

- [ ] **Step 2: Verify syntax and compilation**
  Run: `python -m py_compile proxy_core/server.py`
  Expected: Success with no errors.

---

### Task 2: Implement Detailed Stream Logging and Error Propagation in `proxy_core/server.py`

**Files:**
- Modify: `proxy_core/server.py:1317-1405`

- [ ] **Step 1: Update `stream_generator` and `iter_bytes`**
  Modify `stream_generator` to log stream start, successful completion, client disconnects (`asyncio.CancelledError`), and propagate all exceptions using `raise`.

  *Code change preview:*
  ```python
                    logger.info(f"[{candidate_model}] Starting stream transmission...")
                    response_text_buffer = []
                    raw_chunks_buffer = []

                    async def stream_generator():
                        try:

                            async def iter_bytes():
                                try:
                                    async for chunk in response.aiter_bytes():
                                        if SAVE_CHAT_LOGS:
                                            raw_chunks_buffer.append(chunk)
                                        yield chunk
                                except (httpx.ReadError, httpx.HTTPError) as he:
                                    logger.error(
                                        f"[{candidate_model}] Upstream stream read error (abrupt disconnect or timeout): {he}"
                                    )
                                    raise  # Propagate to prevent silent 200 OK on failure
                                except asyncio.CancelledError:
                                    logger.warning(
                                        f"[{candidate_model}] Stream transmission cancelled by client (OpenCode disconnected)."
                                    )
                                    raise
                                except Exception as se:
                                    logger.error(
                                        f"[{candidate_model}] Unexpected stream exception: {se}"
                                    )
                                    raise

                            async def iter_translated_chunks():
                                async for chunk in iter_bytes():
                                    chunk_str = ""
                                    if (
                                        SAVE_CHAT_LOGS
                                        or needs_gemini_response_translation
                                    ):
                                        try:
                                            chunk_str = chunk.decode(
                                                "utf-8", errors="ignore"
                                            )
                                        except Exception:
                                            pass

                                    if SAVE_CHAT_LOGS and chunk_str:
                                        try:
                                            text_part = extract_text_from_chunk(
                                                chunk_str, provider_name
                                            )
                                            if text_part:
                                                response_text_buffer.append(text_part)
                                        except Exception as ce:
                                            logger.debug(
                                                f"Error extracting text from chunk: {ce}"
                                            )

                                    if needs_gemini_response_translation and chunk_str:
                                        try:
                                            translated_lines = []
                                            for line in chunk_str.split("\n"):
                                                line_stripped = line.strip()
                                                if line_stripped:
                                                    translated_line = translate_openai_chunk_to_gemini(
                                                        line_stripped
                                                    )
                                                    translated_lines.append(
                                                        translated_line
                                                    )
                                                else:
                                                    translated_lines.append(line)
                                            translated_chunk = "\n".join(
                                                translated_lines
                                            )
                                            yield translated_chunk.encode("utf-8")
                                        except Exception as te:
                                            logger.debug(
                                                f"Failed to translate response chunk: {te}"
                                            )
                                            yield chunk
                                    else:
                                        yield chunk

                            async for trans_chunk in iter_translated_chunks():
                                yield trans_chunk

                            logger.info(
                                f"[{candidate_model}] Stream transmission completed successfully. Total chunks: {len(raw_chunks_buffer)}"
                            )
                        except asyncio.CancelledError:
                            logger.warning(
                                f"[{candidate_model}] Stream generator task cancelled."
                            )
                            raise
                        except Exception as e:
                            logger.error(
                                f"[{candidate_model}] Stream generator encountered an error: {e}"
                            )
                            raise
                        finally:
                            await response.aclose()
                            if SAVE_CHAT_LOGS:
                                response_text = "".join(response_text_buffer)
                                raw_req_bytes = body
                                raw_resp_bytes = b"".join(raw_chunks_buffer)
                                asyncio.create_task(
                                    write_chat_log(
                                        model=candidate_model,
                                        provider=provider_name,
                                        messages=req_messages,
                                        response=response_text,
                                        session_id=session_id,
                                        raw_request=raw_req_bytes,
                                        raw_response=raw_resp_bytes,
                                    )
                                )
  ```

- [ ] **Step 2: Verify syntax and compilation**
  Run: `python -m py_compile proxy_core/server.py`
  Expected: Success with no errors.
