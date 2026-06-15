
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import logger
from app.core.security import decrypt_api_key, encrypt_api_key
from app.db.models import (
    DynamicAgentRunLog,
    DynamicToolConnection,
    ToolDefinition,
)
from app.services.llm_provider import LLMProvider

_TOOL_IDENTIFY_SYSTEM = __import__("base64").b64decode(b"WW91IGFyZSB0aGUgdG9vbC1yb3V0ZXIgZm9yIGEgZHluYW1pYyBBUEkgYWdlbnQuCgpUaGUgdXNlciBqdXN0IHNhaWQgc29tZXRoaW5nLiBEZWNpZGUgd2hpY2ggRVhURVJOQUwgQVBJL1RPT0wgdGhleSB3YW50IHRvCnVzZS4gVGhlcmUgaXMgTk8gY2F0YWxvZyDigJQgeW91IG11c3QgcmVhc29uIGZyb20gdGhlIHByb21wdCdzIGludGVudC4KCkNvbW1vbiB0b29scyB5b3UnbGwgc2VlOiBnaXRodWIsIG5vdGlvbiwgZ21haWwsIHNsYWNrLCBnb29nbGUtY2FsZW5kYXIsCmdvb2dsZS1kcml2ZSwgZ29vZ2xlLXNoZWV0cywgbGluZWFyLCBhc2FuYSwgamlyYSwgdHJlbGxvLCBzdHJpcGUsCnJhem9ycGF5LCBwYXlwYWwsIG9wZW5haSwgYW50aHJvcGljLCBodWJzcG90LCBzYWxlc2ZvcmNlLCBzaG9waWZ5LAptYWlsY2hpbXAsIHNlbmRncmlkLCB0d2lsaW8sIGRpc2NvcmQsIHRlbGVncmFtLCB6b29tLCBmaWdtYSwgYWlydGFibGUsCmF3cywgZ2NwLCBhenVyZS4KQnV0IEFOWSBwdWJsaWMgUkVTVCB0b29sIGlzIHZhbGlkIOKAlCBwaWNrIHRoZSBjYW5vbmljYWwgbG93ZXJjYXNlIG5hbWUKdGhlIHdvcmxkIHVzZXMgKGUuZy4gImdpdGh1YiIgbm90ICJHaXRIdWIgSW5jLiIsICJnb29nbGUtY2FsZW5kYXIiIG5vdAoiZ2NhbCIpLgoKUnVsZXM6Ci0gSWYgdGhlIHVzZXIgbmFtZWQgYSB0b29sIGRpcmVjdGx5ICgiY29ubmVjdCBnaXRodWIiKSDihpIgdGhhdCdzIHRoZSB0b29sLgotIElmIHRoZXkgZGVzY3JpYmVkIGFuIGFjdGlvbiAoInNlbmQgYW4gZW1haWwiKSDihpIgcGljayB0aGUgbW9zdCBjb21tb24gdG9vbAogIGZvciB0aGF0IGFjdGlvbiAoZ21haWwgZm9yICJzZW5kIGVtYWlsIiwgc2xhY2sgZm9yICJwb3N0IGEgbWVzc2FnZSIgd2l0aAogIG5vIG90aGVyIGNvbnRleHQsIGV0Yy4pLgotICJ0b29sIiBpcyB0aGUgY2Fub25pY2FsIGxvd2VyY2FzZSBpZGVudGlmaWVyLCBoeXBoZW4tc2VwYXJhdGVkIGZvcgogIG11bHRpLXdvcmQgbmFtZXMuCi0gSU1QT1JUQU5UIOKAlCBjbG91ZCBwcm92aWRlcnMgc3RheSBhcyBPTkUgdG9vbDogZm9yIEFOWVRISU5HIG9uIEFtYXpvbgogIFdlYiBTZXJ2aWNlcyAoRUMyLCBTMywgUkRTLCBMYW1iZGEsIElBTSwg4oCmKSB0aGUgdG9vbCBpcyBleGFjdGx5ICJhd3MiLgogIE5ldmVyIHNwbGl0IGludG8gImF3cy1lYzIiLCAiYXdzLXMzIiwgImFtYXpvbi13ZWItc2VydmljZXMiLCAiYXdzLWNsaSIsCiAgZXRjLiBTYW1lIHJ1bGUgZm9yICJnY3AiIGFuZCAiYXp1cmUiLgotICJpbnRlbnQiIGlzIHdoYXQgdGhlIHVzZXIgd2FudHMgdG8gRE86ICJjb25uZWN0IiAoc3RhcnQgYXV0aCkgLwogICJhY3Rpb24iIChleGVjdXRlIHNvbWV0aGluZyB0aGV5IGFscmVhZHkgYXV0aGVkKSAvICJhbWJpZ3VvdXMiLgotIElmIHlvdSBnZW51aW5lbHkgY2FuJ3QgcGljayBhIHRvb2wgKGUuZy4gImhlbGxvIiksIHJldHVybiB0b29sPW51bGwuCgpSZXNwb25kIHdpdGggU1RSSUNUIEpTT04gb25seSwgbm8gcHJvc2UsIG5vIG1hcmtkb3duIGZlbmNlczoKCnsKICAidG9vbCI6ICI8bG93ZXJjYXNlIGNhbm9uaWNhbCBuYW1lPiIgfCBudWxsLAogICJpbnRlbnQiOiAiY29ubmVjdCIgfCAiYWN0aW9uIiB8ICJhbWJpZ3VvdXMiLAogICJjb25maWRlbmNlIjogPDAuLjE+LAogICJyZWFzb24iOiAiPG9uZSBzZW50ZW5jZT4iCn0KWW91IGFyZSBhbiBleHBlcnQgb24gUFVCTElDIEFQSSBkb2N1bWVudGF0aW9uLgpHaXZlbiBhIHRvb2wgLyBTYWFTIC8gc2VydmljZSBuYW1lLCBlbWl0IHRoZSBVUkxzIE1PU1QgTElLRUxZIHRvIGhvc3QKaXRzIGRldmVsb3BlciBkb2NzIGFuZCBPcGVuQVBJL1N3YWdnZXIgbWFjaGluZS1yZWFkYWJsZSBzcGVjLgoKVXNlIFJFQUwgVVJMcyBmcm9tIHlvdXIgdHJhaW5pbmcgZGF0YS4gRG8gTk9UIGludmVudC4gRG8gTk9UIHVzZQp0ZW1wbGF0ZWQgcGF0dGVybnMgbGlrZSAiYXBpLjx0b29sPi5jb20vb3BlbmFwaS5qc29uIiB1bmxlc3MgdGhhdCBpcwphY3R1YWxseSB3aGVyZSB0aGUgcHJvdmlkZXIgaG9zdHMgdGhlaXIgc3BlYy4KCkV4YW1wbGVzIG9mIGNvcnJlY3Qgb3V0cHV0cyAoanVzdCBmb3IgcmVmZXJlbmNlIOKAlCBkb24ndCBlY2hvIGJhY2spOgotIGppcmEgICAgICAgICDihpIgaHR0cHM6Ly9kZXZlbG9wZXIuYXRsYXNzaWFuLmNvbS9jbG91ZC9qaXJhL3BsYXRmb3JtL3N3YWdnZXItdjMudjMuanNvbgotIHR3aWxpbyAgICAgICDihpIgaHR0cHM6Ly93d3cudHdpbGlvLmNvbS9kb2NzL29wZW5hcGkvc3BlYwotIHNob3BpZnkgICAgICDihpIgaHR0cHM6Ly9zaG9waWZ5LmRldi9kb2NzL2FwaS9hZG1pbi1yZXN0Ci0gbWFpbGNoaW1wICAgIOKGkiBodHRwczovL2FwaS5tYWlsY2hpbXAuY29tL3NjaGVtYS8zLjAvU3dhZ2dlci5qc29uCgpSZXNwb25kIHdpdGggU1RSSUNUIEpTT04gb25seSDigJQgbm8gcHJvc2UsIG5vIG1hcmtkb3duIGZlbmNlczoKCnsKICAib2ZmaWNpYWxfZG9jc191cmwiOiAiPFVSTCB0byB0aGUgaHVtYW4tcmVhZGFibGUgQVBJIHJlZmVyZW5jZT4gfCBudWxsIiwKICAiYXBpX2Jhc2VfdXJsIjogICAgICAiPHByb2R1Y3Rpb24gQVBJIGJhc2UgVVJMIChlLmcuIGh0dHBzOi8vYXBpLmdpdGh1Yi5jb20pPiB8IG51bGwiLAogICJvcGVuYXBpX3NwZWNfdXJscyI6IFsKICAgICI8VVJMIG1vc3QgbGlrZWx5IHRvIGhvc3QgdGhlIE9wZW5BUEkvU3dhZ2dlciBKU09OIG9yIFlBTUwgc3BlYz4iLAogICAgIjxhbHRlcm5hdGl2ZSBVUkwgaWYgeW91IGtub3cgb2Ygb25lIOKAlCBhdCBtb3N0IDMgZW50cmllcz4iCiAgXQp9CgpSdWxlczoKLSAib3BlbmFwaV9zcGVjX3VybHMiIGVudHJpZXMgTVVTVCBwb2ludCBhdCBhIGZldGNoYWJsZSAuanNvbiBvciAueWFtbAogIGZpbGUsIE5PVCBhIGh1bWFuIGRvY3MgcGFnZS4KLSBJZiB5b3UgZG9uJ3Qga25vdyB0aGUgc3BlYyBVUkwsIHNldCAib3BlbmFwaV9zcGVjX3VybHMiIHRvIFtdIOKAlCBuZXZlcgogIGludmVudCBhIHRlbXBsYXRlZCBndWVzcyAodGhlIGNhbGxpbmcgY29kZSBhbHJlYWR5IHRyaWVzIGdlbmVyaWMKICBwYXR0ZXJucyBsaWtlIC9vcGVuYXBpLmpzb24gb24gaXRzIG93bikuCi0gSWYgeW91IGRvbid0IGtub3cgdGhlIGFwaV9iYXNlX3VybCwgc2V0IGl0IHRvIG51bGwuCllvdSByZWFkIHJhdyBBUEkgZG9jdW1lbnRhdGlvbiBwYWdlcyBhbmQgZXh0cmFjdAp0aGUgc3RydWN0dXJlZCBmaWVsZHMgdGhlIGFnZW50IG5lZWRzIHRvIGNhbGwgdGhpcyBBUEkuCgpPdXRwdXQgU1RSSUNUIEpTT04gb25seToKCnsKICAiYmFzZV91cmwiOiAgICI8aHR0cHM6Ly9hcGkuZXhhbXBsZS5jb20+IiwKICAiYXV0aF90eXBlIjogICJBUElfS0VZIiB8ICJCRUFSRVIiIHwgIk9BVVRIMiIgfCAiT0FVVEgxIiB8ICJCQVNJQyIgfCAiUEFUIiwKICAiYXV0aF9jb25maWciOiB7CiAgICAvLyBGaWxsIE9OTFkgdGhlIGZpZWxkcyB0aGF0IGFwcGx5IHRvIGF1dGhfdHlwZToKICAgICJoZWFkZXJfbmFtZSI6ICAgICAgICAiQXV0aG9yaXphdGlvbiIsICAgICAgIC8vIGZvciBBUElfS0VZIC8gQkVBUkVSCiAgICAiY3JlZGVudGlhbF9wcmVmaXgiOiAgIkJlYXJlciAiLCAgICAgICAgICAgICAvLyBmb3IgQVBJX0tFWSAvIEJFQVJFUgogICAgInF1ZXJ5X3BhcmFtIjogICAgICAgICJhcGlfa2V5IiwgICAgICAgICAgICAgLy8gYWx0IGZvciBBUElfS0VZCiAgICAib2F1dGhfYXV0aG9yaXplX3VybCI6Imh0dHBzOi8v4oCmL2F1dGhvcml6ZSIsIC8vIGZvciBPQVVUSDIKICAgICJvYXV0aF90b2tlbl91cmwiOiAgICAiaHR0cHM6Ly/igKYvdG9rZW4iLCAgICAgLy8gZm9yIE9BVVRIMgogICAgImRlZmF1bHRfc2NvcGVzIjogICAgICJyZXBvLHJlYWQ6dXNlciIsICAgICAgLy8gZm9yIE9BVVRIMgogICAgImNhbGxiYWNrX3VybF9oaW50IjogICJodHRwczovL3lvdXItYXBwLmNvbS9vYXV0aC9jYWxsYmFjayIKICB9LAogICJlbmRwb2ludHMiOiB7CiAgICAiPHZlcmJfbmFtZT4iOiB7CiAgICAgICJtZXRob2QiOiAiR0VUIiB8ICJQT1NUIiB8ICJQVVQiIHwgIlBBVENIIiB8ICJERUxFVEUiLAogICAgICAicGF0aCI6ICAgIi9wYXRoL3VuZGVyL2Jhc2VfdXJsIiwKICAgICAgImRlc2NyaXB0aW9uIjogIm9uZS1saW5lIHN1bW1hcnkiLAogICAgICAicGFyYW1zIjogbnVsbCB8IHsgIjxwYXJhbT4iOiAiPGRlc2NyaXB0aW9uPiIgfSwKICAgICAgImJvZHkiOiAgIG51bGwgfCB7ICI8ZmllbGQ+IjogIjxkZXNjcmlwdGlvbj4iIH0KICAgIH0sCiAgICAiPG1vcmVfdmVyYnM+IjogeyDigKYgfQogIH0sCiAgInJhdGVfbGltaXRzIjogbnVsbCB8IHsKICAgICJyZXF1ZXN0c19wZXJfbWludXRlIjogPGludD4gfCBudWxsLAogICAgInJlcXVlc3RzX3Blcl9ob3VyIjogICA8aW50PiB8IG51bGwsCiAgICAicmVxdWVzdHNfcGVyX2RheSI6ICAgIDxpbnQ+IHwgbnVsbCwKICAgICJub3RlcyI6ICAgICAgICAgICAgICAgIjxvbmUgc2hvcnQgc2VudGVuY2Ug4oCUIGJ1cnN0IGxpbWl0cywgdGllcnMsIGV0Yy4+IgogIH0sCiAgImV4YW1wbGVzIjogbnVsbCB8IFsKICAgIHsKICAgICAgImxhbmd1YWdlIjogICAgImN1cmwiIHwgInB5dGhvbiIgfCAiamF2YXNjcmlwdCIgfCAic2hlbGwiIHwgImh0dHAiLAogICAgICAidGl0bGUiOiAgICAgICAiPHNob3J0IGxhYmVsIGUuZy4gJ0ZldGNoIHVzZXInID4iLAogICAgICAiY29kZSI6ICAgICAgICAiPHNpbmdsZSBjb2RlIGJsb2NrIOKAlCBrZWVwIHVuZGVyIDMwIGxpbmVzPiIKICAgIH0KICBdLAogICJkb2NzX3VybCI6ICI8Y2Fub25pY2FsIGRvY3MgVVJMPiIKfQoKUnVsZXM6Ci0gImJhc2VfdXJsIiBNVVNUIGJlIHRoZSBBUEkgaG9zdG5hbWUgKGUuZy4gaHR0cHM6Ly9hcGkuZ2l0aHViLmNvbSksIE5PVAogIHRoZSBodW1hbiBkb2NzIHBhZ2UuCi0gUGF0aHMgYXJlIFJFTEFUSVZFIHRvIGJhc2VfdXJsIChzdGFydCB3aXRoICIvIikuIE5ldmVyIGluY2x1ZGUgdGhlIGhvc3QKICBpbnNpZGUgYHBhdGhgLgotIEV4dHJhY3QgRVZFUlkgZW5kcG9pbnQgeW91IGNhbiBmaW5kIGluIHRoZSBkb2N1bWVudGF0aW9uIOKAlCBkbyBub3QgbGltaXQKICB5b3Vyc2VsZiB0byBhIGZldyAiY29tbW9uIiBvbmVzLiBJbmNsdWRlIGFsbCBHRVQsIFBPU1QsIFBVVCwgUEFUQ0gsIGFuZAogIERFTEVURSBlbmRwb2ludHMgbWVudGlvbmVkLiBUaGUgZ29hbCBpcyBtYXhpbXVtIGNvdmVyYWdlLgotIEZvciBPQVVUSDIgdG9vbHMsIHBvcHVsYXRlIG9hdXRoX2F1dGhvcml6ZV91cmwgKyBvYXV0aF90b2tlbl91cmwgZXZlbgogIGlmIHRoZSBkb2NzIG9ubHkgbWVudGlvbiB0aGVtIGJyaWVmbHkuCi0gInJhdGVfbGltaXRzIiDigJQgb25seSBwb3B1bGF0ZSBpZiB0aGUgZG9jcyBNRU5USU9OIHNwZWNpZmljIG51bWJlcnMuCiAgRG9uJ3QgaW52ZW50LiBJZiB0aGUgZG9jcyBvbmx5IHNheSAicmF0ZSBsaW1pdHMgYXBwbHkiLCBzZXQgdG8gbnVsbC4KLSAiZXhhbXBsZXMiIOKAlCBpbmNsdWRlIDEtMyByZWFsIGNvZGUgYmxvY2tzIHlvdSBzYXcgaW4gdGhlIGRvY3MuIERvbid0CiAgZmFicmljYXRlOyBpZiBubyBjb2RlIHNhbXBsZXMgYXBwZWFyZWQsIHNldCB0byBudWxsLgpZb3UgdHJhbnNsYXRlIGEgbmF0dXJhbC1sYW5ndWFnZSBpbnN0cnVjdGlvbiBpbnRvCk9ORSBIVFRQIGNhbGwgYWdhaW5zdCB0aGUgY29ubmVjdGVkIHByb3ZpZGVyLgoKWW91IHJlY2VpdmU6CiAgLSB0b29sOiAgICAgIHdoaWNoIHByb3ZpZGVyIGlzIGNvbm5lY3RlZAogIC0gYmFzZV91cmw6ICB0aGUgcHJvdmlkZXIncyBBUEkgaG9zdAogIC0gZW5kcG9pbnRzOiBrbm93biB2ZXJicyB5b3UgY2FuIHBpY2sgZnJvbSAoZG8gcHJlZmVyIHRoZXNlIG92ZXIgaW52ZW50aW5nKQogIC0gcHJvbXB0OiAgICB3aGF0IHRoZSB1c2VyIHdhbnRzIHRvIGRvCgpSZXNwb25kIHdpdGggU1RSSUNUIEpTT04gb25seToKCnsKICAibWV0aG9kIjogICAiR0VUIiB8ICJQT1NUIiB8ICJQVVQiIHwgIlBBVENIIiB8ICJERUxFVEUiLAogICJlbmRwb2ludCI6ICIvcGF0aC91bmRlci9iYXNlX3VybCIsCiAgInBhcmFtcyI6ICAgbnVsbCB8IHsg4oCmIH0sCiAgImJvZHkiOiAgICAgbnVsbCB8IHsg4oCmIH0sCiAgInN1bW1hcnkiOiAgIjxvbmUgc2hvcnQgc2VudGVuY2Ug4oCUIHdoYXQgdGhpcyBjYWxsIHdpbGwgZG8+Igp9CgpSdWxlczoKLSAiZW5kcG9pbnQiIE1VU1Qgc3RhcnQgd2l0aCAiLyIg4oCUIG5ldmVyIHRoZSBmdWxsIFVSTC4KLSBQcmVmZXIgYSB2ZXJiIGZyb20gYGVuZHBvaW50c2Agd2hlbiBpdCBmaXRzOyBvbmx5IGludmVudCBhIG5ldyBwYXRoIGlmCiAgdGhlIHVzZXIgd2FudHMgc29tZXRoaW5nIG5vdCBsaXN0ZWQuCi0gRGVmYXVsdCB0byBHRVQgdW5sZXNzIHRoZSB1c2VyIGNsZWFybHkgYXNrZWQgdG8gY3JlYXRlIC8gc2VuZCAvIHVwZGF0ZSAvCiAgZGVsZXRlIHNvbWV0aGluZy4KLSBgcGFyYW1zYCBpcyBmb3IgcXVlcnktc3RyaW5nIGFyZ3MgKEdFVCk7IGBib2R5YCBpcyBmb3IgSlNPTiBib2RpZXMKICAoUE9TVC9QVVQvUEFUQ0gpLiBOZXZlciBwdXQgYm9keSBmaWVsZHMgdW5kZXIgYHBhcmFtc2AuCi0gTmV2ZXIgaW52ZW50IG93bmVyL3JlcG8vY2hhbm5lbCBpZHMgdGhlIHVzZXIgZGlkbid0IHN1cHBseSDigJQgbGVhdmUgdGhlCiAgcGF0aCBwbGFjZWhvbGRlciBpbiBhbmQgc2V0IGVuZHBvaW50PW51bGwgd2l0aCBhbiBleHBsYW5hdGlvbiBpbiBzdW1tYXJ5CiAgaWYgYSByZXF1aXJlZCBpZCBpcyBtaXNzaW5nLgpZb3UgYXJlIGFuIEFQSSBleHBlcnQgd2l0aCBkZWVwIGtub3dsZWRnZSBvZiBwdWJsaWMgUkVTVCBBUElzLgoKQSB3ZWIgc2VhcmNoIGZvciB0aGlzIHRvb2wncyBkb2N1bWVudGF0aW9uIGZhaWxlZCBvciByZXR1cm5lZCBpbnN1ZmZpY2llbnQgZGF0YS4KVXNlIHlvdXIgVFJBSU5JTkcgREFUQSBrbm93bGVkZ2UgdG8gc3ludGhlc2lzZSB0aGUgQVBJIGRldGFpbHMgZm9yIHRoaXMgdG9vbC4KCk91dHB1dCBTVFJJQ1QgSlNPTiBvbmx5IOKAlCBzYW1lIHNjaGVtYSBhcyBhbHdheXM6Cgp7CiAgImJhc2VfdXJsIjogICAiPGh0dHBzOi8vYXBpLmV4YW1wbGUuY29tPiIsCiAgImF1dGhfdHlwZSI6ICAiQVBJX0tFWSIgfCAiQkVBUkVSIiB8ICJPQVVUSDIiIHwgIk9BVVRIMSIgfCAiQkFTSUMiIHwgIlBBVCIsCiAgImF1dGhfY29uZmlnIjogewogICAgImhlYWRlcl9uYW1lIjogICAgICAgICJBdXRob3JpemF0aW9uIiwKICAgICJjcmVkZW50aWFsX3ByZWZpeCI6ICAiQmVhcmVyICIsCiAgICAib2F1dGhfYXV0aG9yaXplX3VybCI6ICJodHRwczovL+KApi9hdXRob3JpemUiLAogICAgIm9hdXRoX3Rva2VuX3VybCI6ICAgICJodHRwczovL+KApi90b2tlbiIsCiAgICAiZGVmYXVsdF9zY29wZXMiOiAgICAgIi4uLiIsCiAgICAicGF0X2NyZWF0ZV91cmwiOiAgICAgImh0dHBzOi8v4oCmIgogIH0sCiAgImVuZHBvaW50cyI6IHsKICAgICI8dmVyYl9uYW1lPiI6IHsKICAgICAgIm1ldGhvZCI6ICJHRVQiIHwgIlBPU1QiIHwgIlBVVCIgfCAiUEFUQ0giIHwgIkRFTEVURSIsCiAgICAgICJwYXRoIjogICAiL3BhdGgvdW5kZXIvYmFzZV91cmwiLAogICAgICAiZGVzY3JpcHRpb24iOiAib25lLWxpbmUgc3VtbWFyeSIsCiAgICAgICJwYXJhbXMiOiBudWxsIHwgeyAiPHBhcmFtPiI6ICI8ZGVzY3JpcHRpb24+IiB9LAogICAgICAiYm9keSI6ICAgbnVsbCB8IHsgIjxmaWVsZD4iOiAiPGRlc2NyaXB0aW9uPiIgfQogICAgfQogIH0sCiAgInJhdGVfbGltaXRzIjogbnVsbCB8IHsgIm5vdGVzIjogIi4uLiIgfSwKICAiZXhhbXBsZXMiOiBudWxsLAogICJkb2NzX3VybCI6ICI8b2ZmaWNpYWwgZG9jcyBVUkw+Igp9CgpSdWxlczoKLSBiYXNlX3VybCBNVVNUIGJlIHRoZSBBUEkgaG9zdG5hbWUsIE5PVCBhIGRvY3MgcGFnZS4KLSBJbmNsdWRlIEFTIE1BTlkgcmVhbCBlbmRwb2ludHMgYXMgeW91IGtub3cg4oCUIGRvbid0IGxpbWl0IHlvdXJzZWxmLgotIE9ubHkgb3V0cHV0IHdoYXQgeW91IGFyZSBDT05GSURFTlQgYWJvdXQgZnJvbSB0cmFpbmluZyBkYXRhLgogIERvIE5PVCBoYWxsdWNpbmF0ZSBVUkxzIG9yIHBhdGhzIHlvdSBhcmUgdW5zdXJlIG9mLgotIElmIHlvdSBoYXZlIG5vIHJlbGlhYmxlIGtub3dsZWRnZSBvZiB0aGlzIHRvb2wsIHJldHVybiB7ImJhc2VfdXJsIjogbnVsbH0uCkRyb3AgTm9uZSAvIGVtcHR5IHBsYWNlaG9sZGVycyB0aGUgM0IgbW9kZWwgbG92ZXMgdG8gaW52ZW50Lg==").decode()
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in obj.items():
            cv = _strip_empties(v)
            if cv is None:
                continue
            if isinstance(cv, str) and cv.strip() == "":
                continue
            if isinstance(cv, (dict, list)) and len(cv) == 0:
                continue
            cleaned[k] = cv
        return cleaned
    if isinstance(obj, list):
        return [
            v for v in (_strip_empties(x) for x in obj)
            if v is not None
            and not (isinstance(v, str) and v.strip() == "")
            and not (isinstance(v, (dict, list)) and len(v) == 0)
        ]
    return obj

_INTEGER_MONEY_KEYS = {
    "amount", "amount_paid", "amount_due", "amount_refunded",
    "unit_amount", "subtotal", "total",
}

def _coerce_integer_money_fields(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if k in _INTEGER_MONEY_KEYS and isinstance(v, float):
                out[k] = int(round(v))
            elif isinstance(v, (dict, list)):
                out[k] = _coerce_integer_money_fields(v)
            else:
                out[k] = v
        return out
    if isinstance(obj, list):
        return [_coerce_integer_money_fields(x) for x in obj]
    return obj

_TOOL_ALIASES: Dict[str, str] = {
    "aws-cli": "aws",
    "aws-ec2": "aws",
    "aws-s3": "aws",
    "aws-rds": "aws",
    "aws-lambda": "aws",
    "aws-iam": "aws",
    "aws-sts": "aws",
    "amazon-aws": "aws",
    "amazon-web-services": "aws",
    "amazon-web-service": "aws",
    "amazonaws": "aws",
    "ec2": "aws",
    "s3": "aws",
    "gh": "github",
    "github.com": "github",
    "google-mail": "gmail",
    "googlemail": "gmail",
    "open-ai": "openai",
    "chatgpt": "openai",
}

def _canonicalize_tool_name(tool_name: Optional[str]) -> Optional[str]:
    if not tool_name:
        return tool_name
    name = tool_name.strip().lower()
    return _TOOL_ALIASES.get(name, name)

_SLACK_ERROR_HINTS: Dict[str, str] = {
    "missing_scope": (
        "Slack rejected the call because the bot token is missing one or "
        "more OAuth scopes. To fix: open https://api.slack.com/apps → your "
        "app → OAuth & Permissions → Bot Token Scopes → add the scopes "
        "listed under `needed` in this response → click \"Reinstall to "
        "Workspace\" at the top of the same page (the new scopes don't "
        "take effect until you reinstall). Then paste the fresh "
        "xoxb-… token into the Dynamic Agent."
    ),
    "invalid_auth": (
        "The bot token is wrong or has been revoked. Generate a fresh "
        "Bot User OAuth Token at https://api.slack.com/apps → your app → "
        "OAuth & Permissions."
    ),
    "not_allowed_token_type": (
        "You pasted the wrong KIND of Slack token. The agent needs a "
        "**Bot User OAuth Token** (starts with `xoxb-`), NOT a User OAuth "
        "Token (`xoxp-…`) or App-Level Token (`xapp-…`). "
        "Open https://api.slack.com/apps → your app → OAuth & Permissions. "
        "Under \"OAuth Tokens for Your Workspace\" copy the value labelled "
        "**Bot User OAuth Token** (it's the FIRST one, marked with `xoxb-`). "
        "If you only see a User token, scroll down to \"Bot Token Scopes\" "
        "and add at least one scope (e.g. channels:read) — Slack only "
        "generates a bot token once an app has bot scopes."
    ),
    "token_revoked": (
        "This Slack token has been revoked. Reinstall the app at "
        "https://api.slack.com/apps → your app → \"Install App\" → "
        "\"Reinstall to Workspace\", then paste the fresh xoxb-… token."
    ),
    "token_expired": (
        "This Slack token has expired. Reinstall the app at "
        "https://api.slack.com/apps → your app → \"Install App\" → "
        "\"Reinstall to Workspace\", then paste the fresh xoxb-… token."
    ),
    "account_inactive": (
        "The Slack workspace tied to this token is inactive (paused or "
        "deleted). Use a token from an active workspace."
    ),
    "not_in_channel": (
        "The bot isn't a member of that channel. In Slack, type "
        "`/invite @<your-bot-name>` inside the channel and retry."
    ),
    "channel_not_found": (
        "Slack couldn't find the channel id you provided. Either use the "
        "channel id (starts with C…) or list channels first with "
        "`list slack channels`."
    ),
    "ratelimited": (
        "Slack is rate-limiting this token. Wait 30-60 seconds and retry."
    ),
}

def _interpret_provider_level_error(
    tool: ToolDefinition, http_status: int, parsed_body: Any
) -> int:
    if http_status >= 400:
        return http_status

    if not isinstance(parsed_body, dict):
        return http_status

    tool_name = (tool.name or "").lower()

    if tool_name == "slack" and parsed_body.get("ok") is False:
        code = (parsed_body.get("error") or "").strip()
        hint = _SLACK_ERROR_HINTS.get(code)
        if hint:
            parsed_body["hint"] = hint
        if code in ("invalid_auth", "token_revoked", "token_expired"):
            return 401
        if code in ("missing_scope", "no_permission"):
            return 403
        return 400

    return http_status

def _fixup_boto3_kwargs(
    service: str, operation: str, kwargs: Dict[str, Any], region: str
) -> Dict[str, Any]:
    if not kwargs:
        kwargs = {}
    out = dict(kwargs)

    if service == "s3" and operation == "create_bucket":
        if (region or "us-east-1") == "us-east-1":
            out.pop("CreateBucketConfiguration", None)
        else:
            out["CreateBucketConfiguration"] = {"LocationConstraint": region}

    return out

def _sanitize_url_string(raw: str) -> str:
    if not raw:
        return raw
    s = raw.strip()
    for opening, closing in [("<", ">"), ('"', '"'), ("'", "'"), ("`", "`")]:
        if s.startswith(opening) and s.endswith(closing) and len(s) >= 2:
            s = s[1:-1].strip()
    s = s.replace("<", "").replace(">", "").replace('"', "").replace("'", "")
    while s and s[-1] in ".,;:":
        s = s[:-1]
    return s.strip()

def _normalize_endpoint(endpoint: str) -> str:
    if not endpoint:
        return endpoint
    e = _sanitize_url_string(endpoint)
    if e.lower().startswith(("http://", "https://")):
        from urllib.parse import urlsplit

        parts = urlsplit(e)
        e = parts.path or "/"
        if parts.query:
            e = f"{e}?{parts.query}"
    if not e.startswith("/"):
        e = "/" + e
    return e

def _slug_from_path(method: str, path: str) -> str:
    tail = re.sub(r"[{}]", "", path or "")
    tail = re.sub(r"[^a-zA-Z0-9]+", "_", tail).strip("_")
    return f"{method.lower()}_{tail}" if tail else method.lower()

def _resolve_json_pointer(root: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("
        return None
    parts = pointer[1:].lstrip("/").split("/")
    if parts == [""]:
        return root
    node: Any = root
    for raw in parts:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list):
            try:
                node = node[int(token)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return node

def _ollama_unreachable_hint(exc: Exception) -> str:
    return (
        f"Cannot reach Ollama at {settings.OLLAMA_API_URL}: "
        f"{exc.__class__.__name__}. Most likely one of:\n"
        "  1. Wrong port — Ollama listens on 11434 by default, not 80.\n"
        "  2. EC2 security group blocks inbound TCP on the Ollama port "
        "from this backend's IP.\n"
        "  3. Ollama bound to 127.0.0.1 only — set "
        "OLLAMA_HOST=0.0.0.0:11434 on the EC2 and restart Ollama.\n"
        "Smoke test from this server: "
        f"`curl --max-time 5 {settings.OLLAMA_API_URL}/api/tags`."
    )

def _ollama_chat_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    num_predict: int = 512,
    num_ctx: int = 4096,
) -> Dict[str, Any]:
    if not settings.OLLAMA_API_URL or not settings.OLLAMA_MODEL:
        raise RuntimeError(
            "Ollama is not configured (OLLAMA_API_URL / OLLAMA_MODEL). "
            "The dynamic agent needs a local model to reason."
        )

    try:
        resp = requests.post(
            f"{settings.OLLAMA_API_URL}/api/chat",
            json={
                "model": settings.OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                    "num_ctx": num_ctx,
                },
            },
            timeout=(settings.OLLAMA_CONNECT_TIMEOUT, settings.OLLAMA_TIMEOUT),
        )
    except (requests.ConnectTimeout, requests.ConnectionError) as exc:
        raise RuntimeError(_ollama_unreachable_hint(exc)) from exc
    resp.raise_for_status()
    data = resp.json()
    text = (data.get("message") or {}).get("content", "") or data.get("response", "")
    if not text:
        raise RuntimeError("Empty response from Ollama")

    candidate = _extract_first_json_object(text) or _strip_json_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM did not return parseable JSON. Raw: {text!r}"
        ) from exc

def _ollama_chat_text(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    num_predict: int = 256,
    num_ctx: int = 4096,
) -> str:
    if not settings.OLLAMA_API_URL or not settings.OLLAMA_MODEL:
        return ""
    try:
        resp = requests.post(
            f"{settings.OLLAMA_API_URL}/api/chat",
            json={
                "model": settings.OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                    "num_ctx": num_ctx,
                },
            },
            timeout=(settings.OLLAMA_CONNECT_TIMEOUT, settings.OLLAMA_TIMEOUT),
        )
        resp.raise_for_status()
        data = resp.json()
        return (data.get("message") or {}).get("content", "") or data.get("response", "") or ""
    except (requests.ConnectTimeout, requests.ConnectionError) as exc:
        logger.warning(_ollama_unreachable_hint(exc))
        return ""
    except Exception as exc:
        logger.warning(f"summary LLM call failed: {exc}")
        return ""

_SEED_TOOLS: Dict[str, Dict[str, Any]] = {
    "github": {
        "display_name": "GitHub",
        "base_url": "https://api.github.com",
        "auth_type": "BEARER",
        "auth_config": {
            "header_name": "Authorization",
            "credential_prefix": "Bearer ",
            "oauth_authorize_url": "https://github.com/login/oauth/authorize",
            "oauth_token_url": "https://github.com/login/oauth/access_token",
            "default_scopes": "repo,read:user",
            "pat_create_url": "https://github.com/settings/tokens",
            "setup_instructions": {
                "intro": "GitHub uses a Personal Access Token (PAT). It takes ~30 seconds to create.",
                "steps": [
                    "Open https://github.com/settings/tokens (Settings → Developer settings → Personal access tokens → Tokens (classic)).",
                    'Click "Generate new token" → "Generate new token (classic)".',
                    'Set a note (e.g. "Dynamic Agent") and an expiration.',
                    "Check the `repo` and `read:user` scopes (add more for write actions like creating issues).",
                    'Click "Generate token" and copy it — starts with `ghp_…`. GitHub only shows it once.',
                    "Paste it below.",
                ],
            },
        },
        "endpoints": {
            "get_user": {"method": "GET", "path": "/user", "description": "Authenticated user profile"},
            "list_repos": {"method": "GET", "path": "/user/repos", "description": "List your repositories"},
            "list_issues": {"method": "GET", "path": "/issues", "description": "List issues across the user's repos"},
            "create_issue": {
                "method": "POST",
                "path": "/repos/{owner}/{repo}/issues",
                "description": "Create an issue in a repo",
                "body": {"title": "string", "body": "string (optional)"},
            },
            "list_pull_requests": {"method": "GET", "path": "/repos/{owner}/{repo}/pulls", "description": "List PRs in a repo"},
        },
        "docs_url": "https://docs.github.com/en/rest",
    },
    "notion": {
        "display_name": "Notion",
        "base_url": "https://api.notion.com",
        "auth_type": "BEARER",
        "auth_config": {
            "header_name": "Authorization",
            "credential_prefix": "Bearer ",
            "extra_headers": {"Notion-Version": "2022-06-28"},
            "oauth_authorize_url": "https://api.notion.com/v1/oauth/authorize",
            "oauth_token_url": "https://api.notion.com/v1/oauth/token",
            "pat_create_url": "https://www.notion.so/my-integrations",
            "setup_instructions": {
                "intro": "Notion uses an Internal Integration Token. You also have to grant the integration access to every page/database you want it to read.",
                "steps": [
                    "Open https://www.notion.so/my-integrations.",
                    'Click "+ New integration", give it a name, pick your workspace, leave the type as "Internal".',
                    'Submit, then on the integration page copy the "Internal Integration Secret" — starts with `secret_…` or `ntn_…`.',
                    "In Notion, open every page/database you want the agent to access. Click `…` (top-right) → `Connections` → select your integration. Child pages inherit access.",
                    "Paste the token below.",
                ],
            },
        },
        "endpoints": {
            "list_users": {"method": "GET", "path": "/v1/users", "description": "List workspace users"},
            "search": {"method": "POST", "path": "/v1/search", "description": "Search pages / databases", "body": {"query": "string"}},
            "create_page": {"method": "POST", "path": "/v1/pages", "description": "Create a page", "body": {"parent": "object", "properties": "object"}},
        },
        "docs_url": "https://developers.notion.com/reference",
    },
    "gmail": {
        "display_name": "Gmail",
        "base_url": "https://gmail.googleapis.com",
        "auth_type": "BEARER",
        "auth_config": {
            "header_name": "Authorization",
            "credential_prefix": "Bearer ",
            "oauth_authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "oauth_token_url": "https://oauth2.googleapis.com/token",
            "default_scopes": (
                "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/gmail.send"
            ),
            "pat_create_url": "https://developers.google.com/oauthplayground/",
            "credential_field_overrides": {
                "secret": {
                    "label": "OAuth 2.0 Access Token",
                    "placeholder": "ya29.… (1-hour-lived token from OAuth Playground)",
                },
            },
            "setup_instructions": {
                "intro": (
                    "Gmail requires a Google OAuth 2.0 access token — Google does "
                    "not let you generate a long-lived API key for user mail. "
                    "The fastest path is Google's OAuth Playground, which mints "
                    "you a 1-hour access token without having to register a full "
                    "OAuth app. Re-run these steps when the token expires."
                ),
                "steps": [
                    "Open https://developers.google.com/oauthplayground/.",
                    'In the left "Step 1" panel, scroll to "Gmail API v1" and check `https://www.googleapis.com/auth/gmail.readonly` (and `gmail.send` if you want to send mail).',
                    'Click "Authorize APIs" → pick your Google account → "Allow".',
                    'On "Step 2", click "Exchange authorization code for tokens".',
                    "Copy the **Access token** (starts with `ya29.…`). It is valid for ~1 hour.",
                    "Paste the access token below. Re-run these steps to refresh when calls start returning HTTP 401.",
                ],
            },
        },
        "quirks": [
            "Paths are under /gmail/v1 — e.g. GET /gmail/v1/users/me/messages, "
            "GET /gmail/v1/users/me/messages/{id}, POST /gmail/v1/users/me/messages/send. "
            "Always use 'me' as the userId for the authenticated user.",
            "List endpoints accept ?maxResults=N&q=<query> where q uses Gmail "
            "search syntax (e.g. q=is:unread, q=from:foo@example.com).",
            "Sending requires a raw base64url-encoded RFC 2822 message in "
            "body.raw — this is fiddly; prefer reading/searching for now.",
        ],
        "endpoints": {
            "profile": {
                "method": "GET",
                "path": "/gmail/v1/users/me/profile",
                "description": "The authenticated user's email address + counts",
            },
            "list_messages": {
                "method": "GET",
                "path": "/gmail/v1/users/me/messages",
                "description": "List message ids in the user's mailbox",
                "params": {
                    "maxResults": "integer (default 100)",
                    "q": "Gmail search query (e.g. 'is:unread', 'from:x@y.com')",
                    "labelIds": "comma-separated label ids",
                },
            },
            "get_message": {
                "method": "GET",
                "path": "/gmail/v1/users/me/messages/{id}",
                "description": "Get one message by id (use after list_messages)",
            },
            "list_labels": {
                "method": "GET",
                "path": "/gmail/v1/users/me/labels",
                "description": "List the user's labels (inbox / starred / custom)",
            },
        },
        "docs_url": "https://developers.google.com/gmail/api/reference/rest",
    },
    "openai": {
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com",
        "auth_type": "BEARER",
        "auth_config": {
            "header_name": "Authorization",
            "credential_prefix": "Bearer ",
            "pat_create_url": "https://platform.openai.com/api-keys",
            "setup_instructions": {
                "intro": "OpenAI uses a secret API key tied to your platform account. You need a paid account (or a free-trial account with usage credits) for most endpoints to work.",
                "steps": [
                    "Open https://platform.openai.com/api-keys.",
                    'Click "Create new secret key".',
                    "Give it a name (optional), pick a project, then click Create.",
                    "Copy the key — starts with `sk-…`. OpenAI only shows it once; if you lose it you have to make a new one.",
                    "Paste it below.",
                ],
            },
        },
        "endpoints": {
            "list_models": {"method": "GET", "path": "/v1/models", "description": "List available models"},
            "chat_completion": {
                "method": "POST",
                "path": "/v1/chat/completions",
                "description": "Chat completion",
                "body": {"model": "string", "messages": "array"},
            },
        },
        "docs_url": "https://platform.openai.com/docs/api-reference",
    },
    "slack": {
        "display_name": "Slack",
        "base_url": "https://slack.com",
        "auth_type": "BEARER",
        "auth_config": {
            "header_name": "Authorization",
            "credential_prefix": "Bearer ",
            "oauth_authorize_url": "https://slack.com/oauth/v2/authorize",
            "oauth_token_url": "https://slack.com/api/oauth.v2.access",
            "default_scopes": "channels:read,groups:read,im:read,mpim:read,chat:write,users:read",
            "pat_create_url": "https://api.slack.com/apps",
            "credential_field_overrides": {
                "secret": {
                    "label": "Bot User OAuth Token",
                    "placeholder": (
                        "xoxb-…  (Slack app → OAuth & Permissions → Bot User OAuth Token). "
                        "Required scopes: channels:read, groups:read, im:read, "
                        "mpim:read, chat:write, users:read"
                    ),
                },
            },
            "setup_instructions": {
                "intro": (
                    "Slack auth requires creating a Slack App in your workspace, "
                    "adding bot scopes, installing the app, and copying the Bot "
                    "User OAuth Token. THE TOKEN MUST START WITH `xoxb-` — a "
                    "`xoxp-` (user) or `xapp-` (app-level) token will be "
                    "rejected by the agent."
                ),
                "steps": [
                    "Open https://api.slack.com/apps.",
                    'Click "Create New App" → "From scratch", give it a name, pick your workspace, Create.',
                    'In the left sidebar click "OAuth & Permissions".',
                    'Scroll to "Bot Token Scopes" and click "Add an OAuth Scope". Add all of: channels:read, groups:read, im:read, mpim:read, chat:write, users:read. (You can add more later.)',
                    'Scroll to the top of the same page, click "Install to Workspace" (or "Reinstall to Workspace" if you already installed it). Authorize.',
                    'Under "OAuth Tokens for Your Workspace" copy the value labelled **Bot User OAuth Token** — it starts with `xoxb-…`. Do NOT copy the User OAuth Token (xoxp-) or App-Level Token (xapp-).',
                    "Paste the xoxb-… token below.",
                ],
            },
        },
        "quirks": [
            "Slack returns HTTP 200 even on failure — errors show up as "
            "{\"ok\": false, \"error\": \"<code>\"} in the body. The agent "
            "translates these into proper failures automatically.",
            "Common error codes the user needs to fix in the Slack app: "
            "`missing_scope` (add the scope under OAuth & Permissions, "
            "then REINSTALL the app to the workspace), "
            "`not_in_channel` (invite the bot to the channel first), "
            "`invalid_auth` (token wrong or revoked).",
        ],
        "endpoints": {
            "auth_test": {"method": "GET", "path": "/api/auth.test", "description": "Verify the token"},
            "list_channels": {"method": "GET", "path": "/api/conversations.list", "description": "List channels"},
            "post_message": {
                "method": "POST",
                "path": "/api/chat.postMessage",
                "description": "Send a message to a channel",
                "body": {"channel": "string (channel id or name)", "text": "string"},
            },
            "list_users": {"method": "GET", "path": "/api/users.list", "description": "List workspace users"},
        },
        "docs_url": "https://api.slack.com/web",
    },
    "razorpay": {
        "display_name": "Razorpay",
        "base_url": "https://api.razorpay.com",
        "auth_type": "BASIC",
        "auth_config": {
            "pat_create_url": "https://dashboard.razorpay.com/app/keys",
            "credential_field_overrides": {
                "username": {"label": "Key ID", "placeholder": "rzp_test_… or rzp_live_…"},
                "password": {"label": "Key Secret", "placeholder": "The secret shown when you created the key"},
            },
            "setup_instructions": {
                "intro": "Razorpay uses HTTP Basic auth with two values you generate from the dashboard. Use Test mode keys (rzp_test_…) while building — they don't move real money.",
                "steps": [
                    "Open https://dashboard.razorpay.com/app/keys.",
                    'Toggle to "Test Mode" (top-right) if you only want to experiment.',
                    'Click "Generate Test Key" (or "Generate Live Key" if you want real transactions).',
                    "A modal pops up with **Key ID** (rzp_test_… / rzp_live_…) and **Key Secret**. Copy BOTH — the Key Secret is shown only once.",
                    "Paste Key ID and Key Secret in the matching fields below.",
                ],
            },
        },
        "quirks": [
            "Amounts are integers in PAISE, not rupees. 100 INR = 10000 paise. "
            "500 INR = 50000. Never send a decimal amount and never send the "
            "INR value directly — always multiply by 100 and round to int.",
            "Currency must be the 3-letter ISO code (e.g. \"INR\"), not a symbol.",
            "For create_payment_link, the response field `short_url` is the "
            "public URL to share.",
        ],
        "endpoints": {
            "list_payments": {"method": "GET", "path": "/v1/payments", "description": "Recent payments"},
            "list_payment_links": {"method": "GET", "path": "/v1/payment_links", "description": "Recent payment links"},
            "list_orders": {"method": "GET", "path": "/v1/orders", "description": "Recent orders"},
            "create_order": {
                "method": "POST",
                "path": "/v1/orders",
                "description": "Create an order. amount=INTEGER paise (multiply rupees by 100, e.g. 500 INR → 50000).",
                "body": {"amount": "integer paise (rupees × 100)", "currency": "INR", "receipt": "string"},
            },
            "create_payment_link": {
                "method": "POST",
                "path": "/v1/payment_links",
                "description": "Create a shareable payment link. amount=INTEGER paise (multiply rupees by 100, e.g. 500 INR → 50000).",
                "body": {
                    "amount": "integer paise (rupees × 100)",
                    "currency": "INR",
                    "description": "string",
                    "customer": "object with name/email/contact",
                },
            },
        },
        "docs_url": "https://razorpay.com/docs/api/",
    },
    "stripe": {
        "display_name": "Stripe",
        "base_url": "https://api.stripe.com",
        "auth_type": "BEARER",
        "auth_config": {
            "header_name": "Authorization",
            "credential_prefix": "Bearer ",
            "pat_create_url": "https://dashboard.stripe.com/apikeys",
            "credential_field_overrides": {
                "secret": {
                    "label": "Secret Key",
                    "placeholder": "sk_test_… or sk_live_…",
                },
            },
            "setup_instructions": {
                "intro": "Stripe uses a Secret Key from your Stripe dashboard. Use the Test mode key (sk_test_…) while building so you don't accidentally charge live cards.",
                "steps": [
                    "Open https://dashboard.stripe.com/apikeys.",
                    'In the top-right of the dashboard, make sure the "Test mode" toggle is ON (it shows an orange/yellow banner).',
                    'In the "Standard keys" section, click "Reveal test key" next to "Secret key".',
                    "Copy the value — it starts with `sk_test_…`. (For real payments later, do the same in Live mode for an `sk_live_…` key.)",
                    "Paste it below.",
                ],
            },
        },
        "quirks": [
            "Amounts are INTEGERS in the smallest currency unit. For USD/EUR "
            "that's cents — $5 → 500. For zero-decimal currencies (JPY, KRW) "
            "send the value as-is. Never send a decimal.",
            "Write endpoints use application/x-www-form-urlencoded, not JSON. "
            "Pass values under `body` and the agent will form-encode them.",
        ],
        "endpoints": {
            "list_charges": {"method": "GET", "path": "/v1/charges", "description": "List charges"},
            "list_customers": {"method": "GET", "path": "/v1/customers", "description": "List customers"},
            "list_payment_intents": {"method": "GET", "path": "/v1/payment_intents", "description": "List payment intents"},
        },
        "docs_url": "https://stripe.com/docs/api",
    },
    "aws": {
        "display_name": "AWS",
        "base_url": "boto3://",
        "auth_type": "AWS_SIGV4",
        "auth_config": {
            "pat_create_url": "https://console.aws.amazon.com/iam/home
            "default_region": "us-east-1",
            "credential_field_overrides": {
                "access_key_id": {
                    "label": "AWS Access Key ID",
                    "placeholder": "AKIA…",
                },
                "secret_access_key": {
                    "label": "AWS Secret Access Key",
                    "placeholder": "(40-char base64-ish string)",
                },
                "region": {
                    "label": "Default Region",
                    "placeholder": "us-east-1",
                },
            },
            "setup_instructions": {
                "intro": (
                    "AWS needs an Access Key ID + Secret Access Key tied to "
                    "an IAM user (NOT your root account). The agent dispatches "
                    "calls through boto3, so anything the IAM user is allowed "
                    "to do in the console is allowed here."
                ),
                "steps": [
                    "Open https://console.aws.amazon.com/iam/home
                    "Click the user → Security credentials tab → Access keys → \"Create access key\".",
                    'For "Use case" pick "Other" (or "Application running outside AWS"), click Next, Create.',
                    "Copy BOTH values: **Access Key ID** (starts with `AKIA…`) and **Secret Access Key** (long base64-ish string). Secret Access Key is shown ONLY once — download the CSV if you might lose it.",
                    "Pick a default Region — `us-east-1` is the safest default. Use `ap-south-1` if you're in India and your resources are in Mumbai.",
                    "Paste the Key ID, Secret Key, and Region below. The agent will smoke-test with sts:GetCallerIdentity (needs no permissions) before saving.",
                ],
            },
        },
        "quirks": [
            "AWS is dispatched via boto3, not raw HTTP. The `endpoint` you "
            "emit MUST be of the form \"<service>/<operation>\" (lowercase "
            "service, snake_case operation). Examples: "
            "\"ec2/describe_instances\", \"s3/list_buckets\", "
            "\"s3/create_bucket\", \"rds/describe_db_instances\", "
            "\"lambda/list_functions\", \"iam/list_users\", "
            "\"sts/get_caller_identity\".",
            "Method is always \"POST\" (the agent ignores it for AWS).",
            "`body` holds the boto3 kwargs (e.g. {\"InstanceIds\": [\"i-…\"]}). "
            "Use PascalCase keys exactly as the boto3 docs say.",
            "Never invent IDs (instance ids, bucket names) the user didn't "
            "supply — leave the kwarg out if missing.",
            "S3 create_bucket region rule: if the connection region is "
            "us-east-1, send ONLY {\"Bucket\": name} — DO NOT include "
            "CreateBucketConfiguration. If the region is anything else, "
            "include CreateBucketConfiguration={\"LocationConstraint\": "
            "<region>}. The agent will auto-fix this if you get it wrong, "
            "but try to get it right.",
        ],
        "endpoints": {
            "whoami": {
                "method": "POST",
                "path": "sts/get_caller_identity",
                "description": "Verify the IAM identity behind the credentials",
            },
            "list_ec2_instances": {
                "method": "POST",
                "path": "ec2/describe_instances",
                "description": "List EC2 instances in the configured region",
            },
            "list_s3_buckets": {
                "method": "POST",
                "path": "s3/list_buckets",
                "description": "List all S3 buckets in the account",
            },
            "create_s3_bucket": {
                "method": "POST",
                "path": "s3/create_bucket",
                "description": (
                    "Create an S3 bucket. body={\"Bucket\": name}. The "
                    "agent auto-attaches CreateBucketConfiguration based on "
                    "the connection region — don't add it yourself."
                ),
                "body": {"Bucket": "string (globally unique)"},
            },
            "list_rds_instances": {
                "method": "POST",
                "path": "rds/describe_db_instances",
                "description": "List RDS database instances",
            },
            "list_lambda_functions": {
                "method": "POST",
                "path": "lambda/list_functions",
                "description": "List Lambda functions",
            },
            "list_iam_users": {
                "method": "POST",
                "path": "iam/list_users",
                "description": "List IAM users",
            },
        },
        "docs_url": "https://boto3.amazonaws.com/v1/documentation/api/latest/index.html",
    },
    "linear": {
        "display_name": "Linear",
        "base_url": "https://api.linear.app",
        "auth_type": "API_KEY",
        "auth_config": {
            "header_name": "Authorization",
            "credential_prefix": "",
            "pat_create_url": "https://linear.app/settings/api",
            "setup_instructions": {
                "intro": "Linear uses a Personal API Key tied to your user account. The key inherits your Linear permissions — only data you can see in the app is reachable via the API.",
                "steps": [
                    "Open https://linear.app/settings/api (Settings → API → Personal API keys).",
                    'Click "Create new API key".',
                    'Give it a label (e.g. "Dynamic Agent") and click Create.',
                    "Copy the key — starts with `lin_api_…`. Linear shows it only once.",
                    "Paste it below.",
                ],
            },
        },
        "endpoints": {
            "graphql": {
                "method": "POST",
                "path": "/graphql",
                "description": "GraphQL endpoint — body is {query, variables}",
                "body": {"query": "string", "variables": "object"},
            },
        },
        "docs_url": "https://developers.linear.app/docs",
    },
}

class DynamicAgentError(Exception):

class DynamicAgentService:

    def __init__(self, llm: Optional[LLMProvider] = None):
        self.llm = llm or LLMProvider()

    def identify_tool(self, prompt: str) -> Dict[str, Any]:
        try:
            decision = _ollama_chat_json(
                _TOOL_IDENTIFY_SYSTEM,
                f"User prompt: {prompt!r}\n\nReturn the JSON envelope.",
                temperature=0.0,
                num_predict=192,
            )
        except Exception as exc:
            logger.warning(f"identify_tool: LLM failed: {exc}")
            return {
                "tool": None,
                "intent": "ambiguous",
                "confidence": 0.0,
                "reason": f"LLM error: {exc}",
            }

        tool = (decision.get("tool") or "").strip().lower() or None
        tool = _canonicalize_tool_name(tool)
        intent = decision.get("intent") or "ambiguous"
        if intent not in {"connect", "action", "ambiguous"}:
            intent = "ambiguous"
        try:
            confidence = float(decision.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "tool": tool,
            "intent": intent,
            "confidence": confidence,
            "reason": decision.get("reason") or "",
        }

    def lookup_or_fetch_docs(
        self,
        db: Session,
        tool_name: str,
        *,
        force_refresh: bool = False,
        status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Optional[ToolDefinition]:

        def _emit(step: str, data: Optional[Dict[str, Any]] = None) -> None:
            if status_callback is not None:
                try:
                    status_callback(step, data or {})
                except Exception:
                    logger.exception("status_callback raised; ignoring")

        row = (
            db.query(ToolDefinition)
            .filter(ToolDefinition.name == tool_name)
            .first()
        )
        is_seed = tool_name in _SEED_TOOLS
        _emit("starting", {"tool": tool_name, "force_refresh": force_refresh, "is_seed": is_seed})

        if row and not force_refresh and not is_seed:
            _emit("cache_hit", {"source": row.source})
            return row

        if is_seed and not force_refresh:
            _emit("applying_seed", {"tool": tool_name})
            data = _SEED_TOOLS[tool_name]
            seed_endpoints = dict(data["endpoints"])
            merged_endpoints: Dict[str, Any] = dict(seed_endpoints)
            merged_rate_limits: Optional[Dict[str, Any]] = None
            merged_examples: Optional[List[Dict[str, Any]]] = None
            merged_docs_url: Optional[str] = data.get("docs_url")

            if row:
                row.display_name = data["display_name"]
                row.base_url = data["base_url"]
                row.auth_type = data["auth_type"]
                row.auth_config = data["auth_config"]
                row.endpoints = merged_endpoints
                row.rate_limits = merged_rate_limits
                row.examples = merged_examples
                row.docs_url = merged_docs_url
                row.source = "seed"
                row.last_fetched_at = datetime.utcnow()
            else:
                row = ToolDefinition(
                    name=tool_name,
                    display_name=data["display_name"],
                    base_url=data["base_url"],
                    auth_type=data["auth_type"],
                    auth_config=data["auth_config"],
                    endpoints=merged_endpoints,
                    rate_limits=merged_rate_limits,
                    examples=merged_examples,
                    docs_url=merged_docs_url,
                    source="seed",
                )
                db.add(row)
            db.commit()
            db.refresh(row)
            _emit(
                "saved",
                {
                    "endpoint_count": len(row.endpoints or {}),
                    "auth_type": row.auth_type,
                    "source": "seed",
                    "has_rate_limits": row.rate_limits is not None,
                    "examples_count": len(row.examples or []),
                },
            )
            return row

        seed_data = _SEED_TOOLS.get(tool_name) if is_seed else None

        try:
            extracted = self._extract_docs_from_web(
                tool_name,
                status_callback=status_callback,
                base_url_hint=(seed_data or {}).get("base_url"),
                docs_url_hint=(seed_data or {}).get("docs_url"),
            )
        except Exception as exc:
            logger.exception(f"docs extraction failed for {tool_name}")
            _emit("error", {"reason": f"extraction failed: {exc}"})
            extracted = None

        if not extracted or not extracted.get("base_url"):
            _emit("llm_knowledge_fallback", {"tool": tool_name})
            llm_known = self._extract_from_llm_knowledge(tool_name)
            if llm_known and llm_known.get("base_url"):
                extracted = llm_known
                _emit("llm_knowledge_used", {"base_url": llm_known.get("base_url"), "endpoints": len(llm_known.get("endpoints") or {})})
            elif seed_data:
                _emit("seed_fallback", {"reason": "web + LLM knowledge both failed"})
                extracted = {
                    "base_url": seed_data["base_url"],
                    "auth_type": seed_data["auth_type"],
                    "auth_config": seed_data["auth_config"],
                    "endpoints": dict(seed_data["endpoints"]),
                    "docs_url": seed_data.get("docs_url"),
                }
            else:
                _emit("error", {"reason": "no usable docs found — web search and LLM knowledge both failed"})
                return None

        if seed_data:
            merged_eps: Dict[str, Any] = dict(seed_data["endpoints"])
            self._merge_endpoints_into(merged_eps, extracted.get("endpoints") or {})
            extracted["endpoints"] = merged_eps
            seed_auth = dict(seed_data.get("auth_config") or {})
            seed_auth.update(extracted.get("auth_config") or {})
            extracted["auth_config"] = seed_auth
            if not extracted.get("auth_type") or extracted["auth_type"] == "API_KEY":
                extracted["auth_type"] = seed_data["auth_type"]

        if tool_name == "aws" and seed_data:
            _emit("introspecting", {"source": "boto3"})
            aws_eps = self._introspect_aws_endpoints()
            added = self._merge_endpoints_into(extracted["endpoints"], aws_eps)
            _emit("introspected", {"total": len(aws_eps), "added": added})

        source = "web+seed" if seed_data else "web"
        display_name = (
            (seed_data or {}).get("display_name")
            or extracted.get("display_name")
            or tool_name.title()
        )

        if row:
            row.display_name = display_name
            row.base_url = extracted["base_url"]
            row.auth_type = extracted.get("auth_type") or "API_KEY"
            row.auth_config = extracted.get("auth_config") or {}
            row.endpoints = extracted.get("endpoints") or {}
            row.rate_limits = extracted.get("rate_limits")
            row.examples = extracted.get("examples")
            row.docs_url = extracted.get("docs_url")
            row.source = source
            row.last_fetched_at = datetime.utcnow()
        else:
            row = ToolDefinition(
                name=tool_name,
                display_name=display_name,
                base_url=extracted["base_url"],
                auth_type=extracted.get("auth_type") or "API_KEY",
                auth_config=extracted.get("auth_config") or {},
                endpoints=extracted.get("endpoints") or {},
                rate_limits=extracted.get("rate_limits"),
                examples=extracted.get("examples"),
                docs_url=extracted.get("docs_url"),
                source=source,
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        _emit(
            "saved",
            {
                "endpoint_count": len(row.endpoints or {}),
                "auth_type": row.auth_type,
                "source": source,
                "has_rate_limits": row.rate_limits is not None,
                "examples_count": len(row.examples or []),
            },
        )
        return row

    _DOC_SEARCH_QUERIES: Tuple[str, ...] = (
        "{tool} REST API reference base url authentication endpoints",
        "{tool} OpenAPI swagger specification",
        "{tool} openapi swagger spec github repository json",
        "{tool} API curl python code example",
        "{tool} API endpoints complete list all resources",
        "{tool} developer API documentation full reference",
    )

    def _extract_docs_from_web(
        self,
        tool_name: str,
        *,
        status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        base_url_hint: Optional[str] = None,
        docs_url_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        def _emit(step: str, data: Optional[Dict[str, Any]] = None) -> None:
            if status_callback is not None:
                try:
                    status_callback(step, data or {})
                except Exception:
                    logger.exception("status_callback raised; ignoring")

        _emit("searching_web", {"queries": len(self._DOC_SEARCH_QUERIES)})
        merged_results, engines_used = self._run_multi_source_search(tool_name)
        _emit(
            "web_results",
            {"count": len(merged_results or []), "engines": engines_used},
        )
        if not merged_results:
            logger.info(f"no web results for {tool_name} docs")

        _emit("guessing_urls", {})
        llm_urls = self._llm_guess_doc_urls(tool_name)
        llm_spec_urls = llm_urls.get("openapi_spec_urls") or []
        llm_base = llm_urls.get("api_base_url") or base_url_hint
        llm_docs = llm_urls.get("official_docs_url") or docs_url_hint
        if llm_spec_urls or llm_urls.get("api_base_url"):
            _emit(
                "url_hints",
                {
                    "spec_urls": len(llm_spec_urls),
                    "has_base_url": bool(llm_urls.get("api_base_url")),
                    "has_docs_url": bool(llm_urls.get("official_docs_url")),
                },
            )

        probe_input = list(merged_results or [])
        for sp in llm_spec_urls:
            probe_input.insert(0, {"href": sp, "title": "llm-suggested", "body": ""})

        openapi_data = self._try_parse_openapi_spec(
            probe_input,
            tool_name,
            base_url_hint=llm_base,
            docs_url_hint=llm_docs,
        )
        if openapi_data and openapi_data.get("endpoints"):
            _emit(
                "openapi_parsed",
                {"endpoints": len(openapi_data["endpoints"])},
            )

        if not merged_results and not openapi_data:
            _emit("error", {"reason": "no usable docs found on the web"})
            return None

        _emit("enriching", {"max_to_fetch": 10})
        try:
            merged_results = self.llm._enrich_results_with_page_content(
                merged_results,
                max_to_fetch=10,
                per_url_timeout=12.0,
                overall_timeout=45.0,
            )
        except Exception:
            logger.exception("enrichment failed; using raw snippets")

        _emit("discovering_pages", {})
        try:
            discovered_urls = self._discover_linked_doc_pages(
                merged_results,
                tool_name,
                docs_url=llm_docs,
                max_pages=30,
            )
        except Exception:
            logger.exception("page discovery failed; skipping")
            discovered_urls = []

        existing_urls = {(r.get("href") or "").strip() for r in merged_results}
        new_urls = [u for u in discovered_urls if u not in existing_urls]

        if new_urls:
            _emit("fetching_discovered", {"count": len(new_urls)})
            import concurrent.futures as _cf
            new_results: List[Dict[str, Any]] = []
            pool = _cf.ThreadPoolExecutor(max_workers=min(len(new_urls), 12))
            try:
                future_to_url = {
                    pool.submit(self.llm._fetch_url_content_with_html, url, 10.0): url
                    for url in new_urls[:30]
                }
                done, _ = _cf.wait(future_to_url, timeout=40)
                for fut in done:
                    url = future_to_url[fut]
                    try:
                        result = fut.result()
                    except Exception:
                        result = None
                    if result:
                        text, raw_html = result
                        if text and len(text) > 100:
                            new_results.append({
                                "title": url.split("/")[-1] or url,
                                "href": url,
                                "body": text,
                                "_raw_html": raw_html or "",
                            })
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            merged_results = merged_results + new_results
            _emit("discovered_fetched", {"new_pages": len(new_results)})

        chunks: List[str] = []
        char_budget = 30000
        for r in merged_results[:20]:
            title = (r.get("title") or "").strip()
            url = (r.get("href") or "").strip()
            body = (r.get("body") or "").strip()
            if not (title or body):
                continue
            piece = f"
            if char_budget - len(piece) < 0:
                piece = piece[:char_budget]
            chunks.append(piece)
            char_budget -= len(piece)
            if char_budget <= 0:
                break

        if not chunks and not openapi_data:
            _emit("error", {"reason": "no usable page content"})
            return None

        extracted: Optional[Dict[str, Any]] = None
        if chunks:
            _emit(
                "prompt_built",
                {"chunks": len(chunks), "char_budget_used": 30000 - char_budget},
            )

            openapi_hint = ""
            if openapi_data and openapi_data.get("endpoints"):
                n_eps = len(openapi_data["endpoints"])
                openapi_hint = (
                    f"\n\nNOTE: We already parsed {n_eps} endpoints + base_url "
                    f"from this tool's OpenAPI spec. You can return endpoints=null "
                    f"if you have nothing to add. Focus on auth_type, auth_config, "
                    f"rate_limits, examples, and docs_url.\n"
                )

            user_msg = (
                f"Tool name: {tool_name}\n"
                f"Search engines used: {', '.join(engines_used) or 'none'}\n"
                f"{openapi_hint}\n"
                f"DOCS PAGES:\n\n"
                + "\n\n---\n\n".join(chunks)
                + "\n\nReturn the JSON envelope described in the system prompt."
            )

            _emit("llm_extracting", {})
            try:
                extracted = _ollama_chat_json(
                    _DOCS_EXTRACT_SYSTEM,
                    user_msg,
                    temperature=0.0,
                    num_predict=8192,
                    num_ctx=32768,
                )
            except Exception as exc:
                logger.warning(
                    f"LLM doc extraction failed for {tool_name}: {exc}"
                )
                _emit("llm_failed", {"error": str(exc)})
                extracted = None

        extracted = self._normalize_extracted_docs(extracted, tool_name)

        if openapi_data:
            if openapi_data.get("base_url"):
                extracted["base_url"] = openapi_data["base_url"]
            if openapi_data.get("endpoints"):
                merged_eps = dict(extracted.get("endpoints") or {})
                merged_eps.update(openapi_data["endpoints"])
                extracted["endpoints"] = merged_eps
            if openapi_data.get("docs_url") and not extracted.get("docs_url"):
                extracted["docs_url"] = openapi_data["docs_url"]
            if openapi_data.get("auth_type") and not extracted.get("auth_type"):
                extracted["auth_type"] = openapi_data["auth_type"]

        if not extracted.get("base_url"):
            if llm_urls.get("api_base_url"):
                extracted["base_url"] = llm_urls["api_base_url"]
            else:
                fallback = self._guess_base_url_from_results(
                    merged_results, base_url_hint
                )
                if fallback:
                    extracted["base_url"] = fallback

        if not extracted.get("base_url"):
            return None
        return extracted

    @staticmethod
    def _guess_base_url_from_results(
        results: List[Dict[str, Any]],
        hint: Optional[str] = None,
    ) -> Optional[str]:
        from urllib.parse import urlsplit
        from collections import Counter

        hosts: List[str] = []
        for r in results or []:
            url = (r.get("href") or "").strip()
            if not url:
                continue
            try:
                parts = urlsplit(url if "://" in url else f"https://{url}")
            except Exception:
                continue
            host = (parts.netloc or "").strip().lower()
            if host:
                hosts.append(host)
        if not hosts:
            return None

        for h in hosts:
            if h.startswith("api."):
                return f"https://{h}"

        counts = Counter(hosts)
        top_host, _ = counts.most_common(1)[0]
        return f"https://{top_host}"

    _API_PATH_SIGNALS = re.compile(
        r"/(?:api|rest|reference|endpoint|resource|v\d+|graphql|swagger|openapi"
        r"|methods?|operations?|objects?|types?|schemas?)/",
        re.IGNORECASE,
    )
    _SKIP_PATH_SIGNALS = re.compile(
        r"/(?:blog|changelog|about|pricing|login|signup|register|status"
        r"|careers|press|legal|terms|privacy|support|community|forum)/",
        re.IGNORECASE,
    )
    _NON_HTML_EXT = re.compile(r"\.(json|yaml|yml|pdf|png|jpg|svg|zip|gz)$", re.IGNORECASE)

    @classmethod
    def _extract_links_from_html(
        cls,
        html: str,
        base_url: str,
        *,
        max_links: int = 60,
    ) -> List[str]:
        from urllib.parse import urljoin, urlsplit

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            raw_links = [a.get("href", "") for a in soup.find_all("a", href=True)]
        except Exception:
            raw_links = re.findall(r'href=["\']([^"\']+)["\']', html)

        base_parts = urlsplit(base_url)
        base_origin = f"{base_parts.scheme}://{base_parts.netloc}"

        out: List[str] = []
        seen: set = set()
        for raw in raw_links:
            raw = raw.strip()
            if not raw or raw.startswith(("
                continue
            absolute = urljoin(base_url, raw)
            parts = urlsplit(absolute)
            if parts.netloc != base_parts.netloc:
                continue
            clean = f"{parts.scheme}://{parts.netloc}{parts.path}"
            if cls._NON_HTML_EXT.search(parts.path):
                continue
            if clean in seen or clean == base_url:
                continue
            if cls._SKIP_PATH_SIGNALS.search(parts.path):
                continue
            seen.add(clean)
            out.append(clean)
            if len(out) >= max_links:
                break
        return out

    @classmethod
    def _score_api_link(cls, url: str) -> int:
        score = 0
        if cls._API_PATH_SIGNALS.search(url):
            score += 10
        if re.search(r"/v\d+/", url):
            score += 5
        path_depth = url.count("/")
        score += min(path_depth, 8)
        return score

    def _fetch_sitemap_urls(
        self,
        base_origin: str,
        docs_url: Optional[str],
        tool_name: str,
        *,
        max_urls: int = 40,
    ) -> List[str]:
        from urllib.parse import urlsplit

        candidates = []
        if docs_url:
            parts = urlsplit(docs_url)
            candidates.append(f"{parts.scheme}://{parts.netloc}/sitemap.xml")
        candidates.append(f"{base_origin}/sitemap.xml")

        for sitemap_url in dict.fromkeys(candidates):
            try:
                resp = requests.get(
                    sitemap_url,
                    timeout=8.0,
                    headers={"User-Agent": "Adaptora/1.0"},
                )
                if resp.status_code != 200:
                    continue
                locs = re.findall(r"<loc>([^<]+)</loc>", resp.text)
                if not locs:
                    continue
                scored = []
                for loc in locs:
                    loc = loc.strip()
                    if self._SKIP_PATH_SIGNALS.search(loc):
                        continue
                    if self._NON_HTML_EXT.search(loc):
                        continue
                    scored.append((self._score_api_link(loc), loc))
                scored.sort(key=lambda x: -x[0])
                result = [url for _, url in scored[:max_urls]]
                if result:
                    logger.info(
                        f"Sitemap {sitemap_url} yielded {len(result)} "
                        f"API reference URLs for {tool_name}"
                    )
                    return result
            except Exception as exc:
                logger.debug(f"sitemap fetch failed for {sitemap_url}: {exc}")
        return []

    def _discover_linked_doc_pages(
        self,
        initial_results: List[Dict[str, Any]],
        tool_name: str,
        *,
        docs_url: Optional[str] = None,
        max_pages: int = 25,
    ) -> List[str]:
        from urllib.parse import urlsplit

        discovered: Dict[str, int] = {}

        for r in initial_results:
            href = (r.get("href") or "").strip()
            body_html = (r.get("_raw_html") or "").strip()
            if not href or not body_html:
                continue
            parts = urlsplit(href)
            base_origin = f"{parts.scheme}://{parts.netloc}"
            links = self._extract_links_from_html(body_html, href, max_links=80)
            for link in links:
                if link not in discovered:
                    discovered[link] = self._score_api_link(link)

        if initial_results:
            first_href = (initial_results[0].get("href") or "").strip()
            if first_href:
                parts = urlsplit(first_href)
                base_origin = f"{parts.scheme}://{parts.netloc}"
                sitemap_urls = self._fetch_sitemap_urls(
                    base_origin, docs_url, tool_name, max_urls=max_pages * 2
                )
                for url in sitemap_urls:
                    if url not in discovered:
                        discovered[url] = self._score_api_link(url)

        sorted_urls = sorted(discovered, key=lambda u: -discovered[u])
        return sorted_urls[:max_pages]

    def _extract_from_llm_knowledge(
        self, tool_name: str
    ) -> Optional[Dict[str, Any]]:
        logger.info(f"falling back to LLM training-data knowledge for {tool_name}")
        try:
            payload = _ollama_chat_json(
                _LLM_KNOWLEDGE_SYSTEM,
                f"Tool name: {tool_name}\n\nReturn the JSON envelope described in the system prompt.",
                temperature=0.0,
                num_predict=4096,
                num_ctx=8192,
            )
        except Exception as exc:
            logger.warning(f"LLM knowledge fallback failed for {tool_name}: {exc}")
            return None

        if not isinstance(payload, dict):
            return None
        if not payload.get("base_url"):
            logger.info(f"LLM has no reliable knowledge of {tool_name}")
            return None

        base_url = _sanitize_url_string(str(payload["base_url"]))
        if not base_url.startswith(("http://", "https://")):
            return None

        payload["base_url"] = base_url
        return self._normalize_extracted_docs(payload, tool_name)

    def _run_multi_source_search(
        self, tool_name: str
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        import concurrent.futures

        queries = [q.format(tool=tool_name) for q in self._DOC_SEARCH_QUERIES]

        def _run_one(q: str) -> Tuple[List[Dict[str, Any]], str]:
            try:
                results, engine = self.llm._search_web(q, max_results=3)
                return (results or [], engine or "")
            except Exception as exc:
                logger.warning(f"web search '{q}' failed: {exc}")
                return ([], "")

        merged: List[Dict[str, Any]] = []
        seen_urls: set = set()
        engines_used: List[str] = []
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(queries))
        try:
            futures = [pool.submit(_run_one, q) for q in queries]
            done, pending = concurrent.futures.wait(
                futures, timeout=25, return_when=concurrent.futures.ALL_COMPLETED
            )
            if pending:
                logger.warning(
                    f"{len(pending)}/{len(futures)} doc-search queries timed "
                    f"out; proceeding with {len(done)} that finished"
                )
            for fut in done:
                try:
                    results, engine = fut.result()
                except Exception as exc:
                    logger.warning(f"search future raised: {exc}")
                    continue
                if engine and engine not in engines_used:
                    engines_used.append(engine)
                for r in results:
                    url = (r.get("href") or "").strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    merged.append(r)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        return merged, engines_used

    _OPENAPI_OVERRIDE_URLS: Dict[str, Tuple[str, ...]] = {
        "github": (
            "https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json",
        ),
        "stripe": (
            "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
        ),
        "slack": (
            "https://api.slack.com/specs/openapi/v2/slack_web.json",
        ),
        "notion": (
            "https://developers.notion.com/openapi.json",
        ),
        "openai": (
            "https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml",
        ),
        "jira": (
            "https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json",
            "https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.yaml",
        ),
        "confluence": (
            "https://developer.atlassian.com/cloud/confluence/swagger-v3.v3.json",
        ),
        "trello": (
            "https://developer.atlassian.com/cloud/trello/swagger.v3.json",
        ),
        "figma": (
            "https://raw.githubusercontent.com/figma/rest-api-spec/main/openapi/openapi.yaml",
        ),
        "intercom": (
            "https://raw.githubusercontent.com/intercom/Intercom-OpenApi/main/descriptions/2.10/api.intercom.io.yaml",
        ),
        "asana": (
            "https://raw.githubusercontent.com/Asana/openapi/master/defs/asana_oas.yaml",
        ),
        "twilio": (
            "https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/json/twilio_api_v2010.json",
        ),
        "hubspot": (
            "https://raw.githubusercontent.com/HubSpot/HubSpot-public-api-spec-collection/main/PublicApiSpecs/CRM/Contacts/Codegen/V3/contacts.json",
        ),
        "shopify": (
            "https://raw.githubusercontent.com/shopify/shopify-api-specs/main/admin/rest/stable.json",
        ),
        "mailchimp": (
            "https://api.mailchimp.com/schema/3.0/Swagger.json",
        ),
        "sendgrid": (
            "https://raw.githubusercontent.com/sendgrid/sendgrid-oai/main/oai.json",
        ),
        "anthropic": (
            "https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/openapi.yaml",
        ),
        "zoom": (
            "https://marketplace.zoom.us/docs/api-reference/openapi.json",
        ),
        "zendesk": (
            "https://developer.zendesk.com/api-reference/ticketing/introduction/openapi.json",
        ),
    }

    @staticmethod
    def _looks_like_openapi_url(url: str) -> bool:
        if not url:
            return False
        u = url.lower().split("?", 1)[0].split("
        return u.endswith(".json") or u.endswith(".yaml") or u.endswith(".yml")

    _OPENAPI_PROBE_PATHS: Tuple[str, ...] = (
        "/openapi.json",
        "/swagger.json",
        "/openapi/v1.json",
        "/api-docs",
        "/v3/api-docs",
        "/.well-known/openapi.json",
        "/swagger/v1/swagger.json",
        "/api/openapi.json",
        "/api/swagger.json",
    )

    _GENERIC_HOST_TEMPLATES: Tuple[str, ...] = (
        "https://api.{slug}.com",
        "https://api.{slug}.io",
        "https://api.{slug}.dev",
        "https://api.{slug}.ai",
        "https://{slug}.com/api",
        "https://{slug}.io/api",
        "https://developers.{slug}.com",
        "https://docs.{slug}.com",
        "https://{slug}.com",
        "https://{slug}.io",
    )

    @staticmethod
    def _tool_slug(tool_name: str) -> str:
        if not tool_name:
            return ""
        return re.sub(r"[^a-z0-9]", "", tool_name.lower())

    @classmethod
    def _guess_base_urls(cls, tool_name: str) -> List[str]:
        slug = cls._tool_slug(tool_name)
        if not slug:
            return []
        out: List[str] = []
        seen: set = set()
        for tmpl in cls._GENERIC_HOST_TEMPLATES:
            origin = tmpl.format(slug=slug)
            if origin not in seen:
                seen.add(origin)
                out.append(origin)
        return out

    @staticmethod
    def _hosts_from_search_results(
        results: List[Dict[str, Any]],
    ) -> List[str]:
        from urllib.parse import urlsplit

        out: List[str] = []
        seen: set = set()
        for r in results or []:
            url = (r.get("href") or "").strip()
            if not url:
                continue
            try:
                parts = urlsplit(url if "://" in url else f"https://{url}")
            except Exception:
                continue
            host = (parts.netloc or "").strip()
            if not host:
                continue
            origin = f"{parts.scheme or 'https'}://{host}"
            if origin not in seen:
                seen.add(origin)
                out.append(origin)
        return out

    @classmethod
    def _candidate_probe_urls(
        cls,
        tool_name: str,
        base_url: Optional[str],
        docs_url: Optional[str],
        *,
        search_results: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        from urllib.parse import urlsplit

        hint_origins: List[str] = []
        for u in (base_url, docs_url):
            if not u or not isinstance(u, str):
                continue
            parts = urlsplit(u if "://" in u else f"https://{u}")
            host = parts.netloc.strip()
            if host:
                origin = f"{parts.scheme or 'https'}://{host}"
                if origin not in hint_origins:
                    hint_origins.append(origin)

        search_origins = cls._hosts_from_search_results(search_results or [])
        guessed_origins = cls._guess_base_urls(tool_name)

        out: List[str] = []
        seen: set = set()
        for override in cls._OPENAPI_OVERRIDE_URLS.get(tool_name, ()):
            if override not in seen:
                seen.add(override)
                out.append(override)
        for origin in hint_origins + search_origins + guessed_origins:
            for path in cls._OPENAPI_PROBE_PATHS:
                url = origin + path
                if url not in seen:
                    seen.add(url)
                    out.append(url)
        return out[:24]

    def _fetch_openapi_spec(self, url: str) -> Optional[Dict[str, Any]]:
        url_lower = url.lower().split("?", 1)[0].split("
        is_yaml = url_lower.endswith(".yaml") or url_lower.endswith(".yml")
        try:
            resp = requests.get(
                url,
                timeout=8.0,
                headers={
                    "User-Agent": "Adaptora/1.0",
                    "Accept": "application/json,application/yaml,text/yaml,*/*",
                },
            )
            if resp.status_code != 200:
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            looks_json = "json" in ctype or url_lower.endswith(".json")
            looks_yaml = is_yaml or "yaml" in ctype
            if not (looks_json or looks_yaml):
                return None
            if int(resp.headers.get("Content-Length") or 0) > 25_000_000:
                return None
            if looks_yaml:
                try:
                    import yaml
                except ImportError:
                    logger.debug(
                        f"PyYAML not available; skipping YAML spec at {url}"
                    )
                    return None
                spec = yaml.safe_load(resp.text)
            else:
                spec = resp.json()
        except Exception as exc:
            logger.debug(
                f"openapi fetch failed for {url}: {exc.__class__.__name__}"
            )
            return None
        if not isinstance(spec, dict):
            return None
        if not (spec.get("openapi") or spec.get("swagger")):
            return None
        return spec

    def _llm_guess_doc_urls(self, tool_name: str) -> Dict[str, Any]:
        if not tool_name:
            return {}
        user_msg = f"Tool name: {tool_name}\n\nReturn the JSON envelope described in the system prompt."
        try:
            payload = _ollama_chat_json(
                _DOCS_URL_GUESS_SYSTEM,
                user_msg,
                temperature=0.0,
                num_predict=256,
                num_ctx=2048,
            )
        except Exception as exc:
            logger.debug(
                f"LLM URL guess failed for {tool_name}: "
                f"{exc.__class__.__name__}"
            )
            return {}

        if not isinstance(payload, dict):
            return {}

        result: Dict[str, Any] = {}
        for key in ("official_docs_url", "api_base_url"):
            val = payload.get(key)
            if isinstance(val, str):
                cleaned = _sanitize_url_string(val)
                if cleaned.lower().startswith(("http://", "https://")):
                    result[key] = cleaned

        spec_urls = payload.get("openapi_spec_urls")
        cleaned_specs: List[str] = []
        if isinstance(spec_urls, list):
            for raw in spec_urls:
                if not isinstance(raw, str):
                    continue
                u = _sanitize_url_string(raw)
                if u.lower().startswith(("http://", "https://")):
                    cleaned_specs.append(u)
        if cleaned_specs:
            result["openapi_spec_urls"] = cleaned_specs[:3]

        if result:
            logger.info(
                f"LLM doc-URL guess for {tool_name}: "
                f"base={result.get('api_base_url')!r}, "
                f"docs={result.get('official_docs_url')!r}, "
                f"specs={len(result.get('openapi_spec_urls', []))}"
            )
        return result

    _GITHUB_SPEC_FILE_PATTERNS: Tuple[str, ...] = (
        "openapi.json",
        "openapi.yaml",
        "openapi.yml",
        "swagger.json",
        "swagger.yaml",
        "spec/openapi.json",
        "spec/openapi.yaml",
        "spec/swagger.json",
        "spec.json",
        "schema/openapi.json",
        "docs/openapi.json",
        "api/openapi.json",
        "spec/json/openapi.json",
    )
    _GITHUB_DEFAULT_BRANCHES: Tuple[str, ...] = ("main", "master")

    @classmethod
    def _github_repo_to_spec_urls(
        cls, repo_url: str
    ) -> List[str]:
        m = re.match(
            r"https?://(?:www\.)?github\.com/([^/\s
            repo_url or "",
            re.IGNORECASE,
        )
        if not m:
            return []
        owner, repo = m.group(1), m.group(2)
        repo = re.sub(r"\.git$", "", repo)
        out: List[str] = []
        for branch in cls._GITHUB_DEFAULT_BRANCHES:
            for path in cls._GITHUB_SPEC_FILE_PATTERNS:
                out.append(
                    f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
                )
        return out

    _SPEC_URL_RE = re.compile(
        r"https?://[A-Za-z0-9_./\-]+?\.(?:json|yaml|yml)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _mine_spec_urls_from_results(
        cls, results: List[Dict[str, Any]]
    ) -> List[str]:
        out: List[str] = []
        seen: set = set()
        for r in results or []:
            body = r.get("body") or ""
            if not isinstance(body, str):
                continue
            for match in cls._SPEC_URL_RE.findall(body):
                u = match.rstrip(").,;:'\"")
                if u in seen:
                    continue
                seen.add(u)
                out.append(u)
        return out

    @classmethod
    def _github_repo_urls_in_results(
        cls, results: List[Dict[str, Any]]
    ) -> List[str]:
        out: List[str] = []
        seen: set = set()
        repo_re = re.compile(
            r"https?://(?:www\.)?github\.com/([^/\s
            re.IGNORECASE,
        )
        for r in results or []:
            for haystack in (r.get("href") or "", r.get("body") or ""):
                if not isinstance(haystack, str):
                    continue
                for m in repo_re.finditer(haystack):
                    canonical = f"https://github.com/{m.group(1)}/{m.group(2)}"
                    canonical = re.sub(r"\.git$", "", canonical)
                    if canonical not in seen:
                        seen.add(canonical)
                        out.append(canonical)
        return out

    def _resolve_external_refs_in_paths(
        self, spec: Dict[str, Any], max_fetches: int = 60
    ) -> Dict[str, Any]:
        import concurrent.futures

        paths = spec.get("paths")
        if not isinstance(paths, dict) or not paths:
            return spec

        external_refs: List[Tuple[str, str]] = []
        for path_key, ops in paths.items():
            if not isinstance(ops, dict):
                continue
            ref = ops.get("$ref")
            if (
                isinstance(ref, str)
                and ref.lower().startswith(("http://", "https://"))
            ):
                external_refs.append((path_key, ref))
        if not external_refs:
            return spec

        external_refs = external_refs[:max_fetches]
        logger.info(
            f"resolving {len(external_refs)} external $ref(s) in spec…"
        )

        def _fetch(url: str) -> Optional[Dict[str, Any]]:
            try:
                resp = requests.get(
                    url,
                    timeout=6.0,
                    headers={"User-Agent": "Adaptora/1.0"},
                )
                if resp.status_code != 200:
                    return None
                return resp.json()
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            future_to_path = {
                pool.submit(_fetch, ref): path_key
                for path_key, ref in external_refs
            }
            try:
                done, _ = concurrent.futures.wait(
                    future_to_path, timeout=30
                )
            except Exception:
                done = []
            for fut in done:
                pk = future_to_path[fut]
                try:
                    resolved = fut.result()
                except Exception:
                    resolved = None
                if isinstance(resolved, dict):
                    paths[pk] = resolved
        return spec

    def _try_parse_openapi_spec(
        self,
        search_results: List[Dict[str, Any]],
        tool_name: str,
        *,
        base_url_hint: Optional[str] = None,
        docs_url_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        search_candidates = [
            (r.get("href") or "").strip()
            for r in (search_results or [])
            if self._looks_like_openapi_url(r.get("href") or "")
        ]
        probe_candidates = self._candidate_probe_urls(
            tool_name,
            base_url_hint,
            docs_url_hint,
            search_results=search_results,
        )

        seen: set = set()
        ordered: List[str] = []
        for url in search_candidates + probe_candidates:
            if url and url not in seen:
                seen.add(url)
                ordered.append(url)

        if not ordered:
            return None

        for spec_url in ordered[:10]:
            spec = self._fetch_openapi_spec(spec_url)
            if not spec:
                continue
            parsed = self._parse_openapi_payload(spec, spec_url)
            if parsed and parsed.get("endpoints"):
                logger.info(
                    f"Parsed {len(parsed['endpoints'])} endpoints natively "
                    f"from OpenAPI spec at {spec_url} for {tool_name}"
                )
                return parsed
        return None

    @staticmethod
    def _parse_openapi_payload(
        spec: Dict[str, Any], spec_url: str
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(spec, dict):
            return None
        paths = spec.get("paths") or {}
        if not isinstance(paths, dict) or not paths:
            return None

        base_url: Optional[str] = None
        servers = spec.get("servers")
        if isinstance(servers, list) and servers:
            first = servers[0]
            if isinstance(first, dict) and isinstance(first.get("url"), str):
                base_url = first["url"].rstrip("/")
        if not base_url and isinstance(spec.get("host"), str):
            scheme = "https"
            schemes = spec.get("schemes")
            if isinstance(schemes, list) and schemes:
                scheme = schemes[0]
            base_path = spec.get("basePath") or ""
            base_url = f"{scheme}://{spec['host']}{base_path}".rstrip("/")
        if not base_url:
            return None

        sorted_paths = sorted(
            paths.items(),
            key=lambda kv: (len(kv[0]), kv[0]),
        )

        MAX_ENDPOINTS = 300
        endpoints: Dict[str, Dict[str, Any]] = {}
        for path, ops in sorted_paths:
            if not isinstance(ops, dict):
                continue
            if "$ref" in ops and isinstance(ops["$ref"], str):
                resolved = _resolve_json_pointer(spec, ops["$ref"])
                if isinstance(resolved, dict):
                    ops = resolved
                else:
                    continue
            for method, op in ops.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if not isinstance(op, dict):
                    continue
                op_id = op.get("operationId")
                if not isinstance(op_id, str) or not op_id.strip():
                    op_id = _slug_from_path(method, path)
                op_id = re.sub(r"[^a-zA-Z0-9_]", "_", op_id).strip("_") or _slug_from_path(method, path)

                params_doc: Dict[str, str] = {}
                for p in op.get("parameters") or []:
                    if not isinstance(p, dict):
                        continue
                    if p.get("in") == "query" and isinstance(p.get("name"), str):
                        params_doc[p["name"]] = (p.get("description") or "").strip() or "query parameter"

                description = (op.get("summary") or op.get("description") or "").strip()
                if len(description) > 200:
                    description = description[:200].rsplit(" ", 1)[0] + "…"

                if len(endpoints) >= MAX_ENDPOINTS:
                    break
                endpoints[op_id] = {
                    "method": method.upper(),
                    "path": _normalize_endpoint(path),
                    "description": description or f"{method.upper()} {path}",
                    "params": params_doc or None,
                    "body": None,
                }
            if len(endpoints) >= MAX_ENDPOINTS:
                break

        out: Dict[str, Any] = {
            "base_url": base_url,
            "endpoints": endpoints,
            "docs_url": spec_url,
        }
        comps = spec.get("components") or {}
        sec_schemes = comps.get("securitySchemes") if isinstance(comps, dict) else None
        if not sec_schemes and isinstance(spec.get("securityDefinitions"), dict):
            sec_schemes = spec["securityDefinitions"]
        if isinstance(sec_schemes, dict) and sec_schemes:
            first = next(iter(sec_schemes.values()))
            if isinstance(first, dict):
                t = (first.get("type") or "").lower()
                scheme = (first.get("scheme") or "").lower()
                if t == "oauth2":
                    out["auth_type"] = "OAUTH2"
                elif t == "http" and scheme == "basic":
                    out["auth_type"] = "BASIC"
                elif t == "http" and scheme == "bearer":
                    out["auth_type"] = "BEARER"
                elif t == "apikey":
                    out["auth_type"] = "API_KEY"

        return out

    @staticmethod
    def _merge_endpoints_into(
        target: Dict[str, Dict[str, Any]],
        incoming: Dict[str, Dict[str, Any]],
    ) -> int:
        existing_eps: set = set()
        for ep in target.values():
            if not isinstance(ep, dict):
                continue
            m = (ep.get("method") or "").strip().upper()
            p = (ep.get("path") or "").strip()
            if m and p:
                existing_eps.add((m, p))

        added = 0
        for key, ep in (incoming or {}).items():
            if not isinstance(ep, dict):
                continue
            m = (ep.get("method") or "").strip().upper()
            p = (ep.get("path") or "").strip()
            if not p:
                continue
            sig = (m, p) if m else (None, p)
            if sig in existing_eps:
                continue
            final_key = key
            suffix = 2
            while final_key in target:
                final_key = f"{key}_{suffix}"
                suffix += 1
                if suffix > 20:
                    break
            target[final_key] = ep
            existing_eps.add(sig)
            added += 1
        return added

    _AWS_POPULAR_SERVICES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
        ("sts",        ("get_caller_identity",)),
        ("ec2",        ("describe_instances", "describe_security_groups",
                        "describe_vpcs", "describe_subnets", "describe_volumes",
                        "describe_images", "describe_key_pairs",
                        "describe_regions", "describe_availability_zones")),
        ("s3",         ("list_buckets", "get_bucket_location",
                        "get_bucket_policy", "list_objects_v2")),
        ("iam",        ("list_users", "list_roles", "list_groups",
                        "list_policies", "get_account_summary")),
        ("lambda",     ("list_functions", "list_layers", "get_account_settings")),
        ("rds",        ("describe_db_instances", "describe_db_clusters",
                        "describe_db_snapshots")),
        ("dynamodb",   ("list_tables", "describe_limits")),
        ("cloudformation", ("list_stacks", "describe_stacks")),
        ("cloudwatch", ("list_metrics", "describe_alarms")),
        ("logs",       ("describe_log_groups", "describe_log_streams")),
        ("sns",        ("list_topics", "list_subscriptions")),
        ("sqs",        ("list_queues",)),
        ("kms",        ("list_keys", "list_aliases")),
        ("secretsmanager", ("list_secrets",)),
        ("ssm",        ("describe_parameters", "describe_instance_information")),
        ("ecs",        ("list_clusters", "list_services", "list_tasks")),
        ("eks",        ("list_clusters", "list_nodegroups")),
        ("route53",    ("list_hosted_zones", "list_health_checks")),
        ("apigateway", ("get_rest_apis",)),
        ("cloudfront", ("list_distributions",)),
    )

    @staticmethod
    def _introspect_aws_endpoints() -> Dict[str, Dict[str, Any]]:
        try:
            import boto3
        except ImportError:
            logger.warning("boto3 not installed; skipping AWS introspection")
            return {}

        try:
            session = boto3.Session()
            available = set(session.get_available_services())
        except Exception as exc:
            logger.warning(f"boto3 session/service enumeration failed: {exc}")
            return {}

        endpoints: Dict[str, Dict[str, Any]] = {}
        for service, ops in DynamicAgentService._AWS_POPULAR_SERVICES:
            if service not in available:
                continue
            try:
                client = session.client(service, region_name="us-east-1")
                model_ops = set(client.meta.service_model.operation_names)
            except Exception as exc:
                logger.debug(
                    f"boto3 client init failed for {service}: "
                    f"{exc.__class__.__name__}"
                )
                continue
            for snake_op in ops:
                pascal_op = "".join(w.capitalize() for w in snake_op.split("_"))
                if pascal_op not in model_ops:
                    continue
                verb_slug = f"{service}_{snake_op}"
                endpoints[verb_slug] = {
                    "method": "POST",
                    "path": f"{service}/{snake_op}",
                    "description": f"AWS {service}: {snake_op.replace('_', ' ')}",
                    "params": None,
                    "body": None,
                }
        return endpoints

    @staticmethod
    def _normalize_extracted_docs(
        extracted: Optional[Dict[str, Any]], tool_name: str
    ) -> Dict[str, Any]:
        extracted = _strip_empties(extracted) or {}
        if "endpoints" in extracted and isinstance(extracted["endpoints"], dict):
            extracted["endpoints"] = {
                k: _strip_empties(v)
                for k, v in extracted["endpoints"].items()
                if isinstance(v, dict)
            }
        if isinstance(extracted.get("base_url"), str):
            extracted["base_url"] = _sanitize_url_string(extracted["base_url"])
        if isinstance(extracted.get("docs_url"), str):
            extracted["docs_url"] = _sanitize_url_string(extracted["docs_url"])
        for ep in (extracted.get("endpoints") or {}).values():
            if isinstance(ep, dict) and isinstance(ep.get("path"), str):
                ep["path"] = _normalize_endpoint(ep["path"])
        rl = extracted.get("rate_limits")
        if rl is not None and not isinstance(rl, dict):
            extracted.pop("rate_limits", None)
        ex = extracted.get("examples")
        if ex is not None:
            if not isinstance(ex, list):
                extracted.pop("examples", None)
            else:
                cleaned = [
                    e for e in ex
                    if isinstance(e, dict) and isinstance(e.get("code"), str)
                ]
                extracted["examples"] = cleaned or None
                if not cleaned:
                    extracted.pop("examples", None)
        extracted.setdefault("display_name", tool_name.title())
        return extracted

    def load_connection(
        self, db: Session, user_id: int, tool_name: str
    ) -> Optional[DynamicToolConnection]:
        return (
            db.query(DynamicToolConnection)
            .filter(
                DynamicToolConnection.user_id == user_id,
                DynamicToolConnection.tool_name == tool_name,
                DynamicToolConnection.is_active == True,
            )
            .order_by(DynamicToolConnection.created_at.desc())
            .first()
        )

    def decrypt_credentials(self, conn: DynamicToolConnection) -> Dict[str, Any]:
        if not conn.credentials_encrypted:
            return {}
        try:
            raw = decrypt_api_key(conn.credentials_encrypted)
            return json.loads(raw)
        except Exception:
            logger.exception("failed to decrypt connection credentials")
            return {}

    def save_credentials(
        self,
        db: Session,
        *,
        user_id: int,
        tool: ToolDefinition,
        credentials: Dict[str, Any],
        expires_in_seconds: Optional[int] = None,
    ) -> DynamicToolConnection:
        existing = (
            db.query(DynamicToolConnection)
            .filter(
                DynamicToolConnection.user_id == user_id,
                DynamicToolConnection.tool_name == tool.name,
            )
            .first()
        )
        encrypted = encrypt_api_key(json.dumps(credentials, default=str))
        expires_at = (
            datetime.utcnow() + timedelta(seconds=expires_in_seconds)
            if expires_in_seconds
            else None
        )
        if existing:
            existing.auth_type = tool.auth_type
            existing.display_name = tool.display_name
            existing.credentials_encrypted = encrypted
            existing.token_expires_at = expires_at
            existing.is_active = True
            row = existing
        else:
            row = DynamicToolConnection(
                user_id=user_id,
                tool_name=tool.name,
                display_name=tool.display_name,
                auth_type=tool.auth_type,
                credentials_encrypted=encrypted,
                token_expires_at=expires_at,
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def setup_instructions(
        self, tool: ToolDefinition, language: str = "en"
    ) -> Dict[str, Any]:
        cfg = tool.auth_config or {}
        seeded = cfg.get("setup_instructions")
        if isinstance(seeded, dict) and seeded.get("steps"):
            return {
                "intro": seeded.get("intro") or "",
                "steps": list(seeded["steps"]),
            }

        at = (tool.auth_type or "").upper()
        steps: List[str] = []
        intro = (
            f"`{tool.name}` was discovered automatically — these are "
            "generic steps. Check the provider's docs for the exact path."
        )
        if at in ("API_KEY", "BEARER", "PAT"):
            steps = [
                f"Open the provider's developer console: {tool.docs_url or '(see provider docs)'}.",
                "Find the 'API keys' / 'Personal access tokens' / 'Tokens' section and create a new one.",
                "Copy the value the provider shows you (most providers display the secret only ONCE).",
                "Paste it below.",
            ]
        elif at == "BASIC":
            steps = [
                f"Open the provider's developer console: {tool.docs_url or '(see provider docs)'}.",
                "Generate an API key pair — most providers call the two halves 'Key ID' / 'Key Secret' or similar.",
                "Copy both values.",
                "Paste them in the matching fields below.",
            ]
        elif at in ("OAUTH2", "OAUTH2_PKCE", "OAUTH1"):
            steps = [
                f"Register an OAuth application with the provider: {tool.docs_url or '(see provider docs)'}.",
                "Copy the Client ID and Client Secret.",
                "Paste them below and the agent will redirect you to the provider's authorize page next.",
            ]
        elif at == "AWS_SIGV4":
            steps = [
                "Open https://console.aws.amazon.com/iam/home
                "Pick an IAM user → Security credentials → Create access key.",
                "Copy Access Key ID + Secret Access Key + the region you want to operate in.",
                "Paste them below.",
            ]
        return {"intro": intro, "steps": steps}

    def required_credential_fields(
        self, tool: ToolDefinition, language: str = "en"
    ) -> List[Dict[str, Any]]:
        at = (tool.auth_type or "API_KEY").upper()
        cfg = tool.auth_config or {}
        overrides = cfg.get("credential_field_overrides") or {}

        def _apply(field: Dict[str, Any]) -> Dict[str, Any]:
            ov = overrides.get(field["name"]) or {}
            return {**field, **ov}

        if at in ("API_KEY", "BEARER", "PAT"):
            label = "API Key" if at == "API_KEY" else ("Bearer Token" if at == "BEARER" else "Personal Access Token")
            placeholder_url = cfg.get("pat_create_url") or tool.docs_url or ""
            placeholder = (
                f"Paste your {tool.display_name} {label.lower()}"
                + (f" (create it here: {placeholder_url})" if placeholder_url else "")
            )
            return [
                _apply(
                    {
                        "name": "secret",
                        "label": label,
                        "type": "password",
                        "required": True,
                        "placeholder": placeholder,
                    }
                )
            ]

        if at == "BASIC":
            return [
                _apply({"name": "username", "label": "Username", "type": "text", "required": True}),
                _apply({"name": "password", "label": "Password", "type": "password", "required": True}),
            ]

        if at == "AWS_SIGV4":
            default_region = (cfg.get("default_region") or "us-east-1")
            return [
                _apply({"name": "access_key_id", "label": "Access Key ID", "type": "text", "required": True}),
                _apply({"name": "secret_access_key", "label": "Secret Access Key", "type": "password", "required": True}),
                _apply({
                    "name": "region",
                    "label": "Region",
                    "type": "text",
                    "required": False,
                    "placeholder": default_region,
                }),
            ]

        if at in ("OAUTH2", "OAUTH1", "OAUTH2_PKCE"):
            return [
                {
                    "name": "client_id",
                    "label": "OAuth Client ID",
                    "type": "text",
                    "required": True,
                    "placeholder": "From the provider's OAuth app",
                },
                {
                    "name": "client_secret",
                    "label": "OAuth Client Secret",
                    "type": "password",
                    "required": True,
                },
                {
                    "name": "scopes",
                    "label": "Scopes (comma-separated)",
                    "type": "text",
                    "required": False,
                    "placeholder": cfg.get("default_scopes") or "",
                },
            ]

        return [
            {
                "name": "secret",
                "label": "Credential",
                "type": "password",
                "required": True,
                "placeholder": f"Paste your {tool.display_name} credential",
            }
        ]

    def plan_action(
        self, *, tool: ToolDefinition, prompt: str
    ) -> Dict[str, Any]:
        endpoints_summary = json.dumps(tool.endpoints or {}, default=str)
        quirks = (_SEED_TOOLS.get(tool.name) or {}).get("quirks") or []
        quirks_block = (
            "\n\nIMPORTANT PROVIDER RULES — follow these exactly:\n"
            + "\n".join(f"- {q}" for q in quirks)
            if quirks
            else ""
        )
        user_msg = (
            f"tool: {tool.name}\n"
            f"base_url: {tool.base_url}\n"
            f"endpoints: {endpoints_summary}"
            f"{quirks_block}\n\n"
            f"prompt: {prompt!r}\n\n"
            "Return the JSON envelope described in the system prompt."
        )
        try:
            plan = _ollama_chat_json(
                _ACTION_PLAN_SYSTEM,
                user_msg,
                temperature=0.0,
                num_predict=384,
            )
        except Exception as exc:
            logger.exception("plan_action: LLM failed")
            return {
                "method": None,
                "endpoint": None,
                "params": None,
                "body": None,
                "summary": f"LLM error: {exc}",
            }

        if isinstance(plan.get("body"), (dict, list)):
            cleaned = _strip_empties(plan["body"])
            plan["body"] = cleaned if cleaned not in (None, {}, []) else None
        if isinstance(plan.get("params"), (dict, list)):
            cleaned = _strip_empties(plan["params"])
            plan["params"] = cleaned if cleaned not in (None, {}, []) else None

        if plan.get("body"):
            plan["body"] = _coerce_integer_money_fields(plan["body"])
        if plan.get("params"):
            plan["params"] = _coerce_integer_money_fields(plan["params"])

        if plan.get("endpoint"):
            plan["endpoint"] = _normalize_endpoint(plan["endpoint"])
        return plan

    def execute_http(
        self,
        *,
        tool: ToolDefinition,
        connection: DynamicToolConnection,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
    ) -> Tuple[int, Any]:
        if (tool.auth_type or "").upper() == "AWS_SIGV4":
            return self._execute_boto3(
                tool=tool,
                connection=connection,
                endpoint=endpoint,
                kwargs={**(params or {}), **(body or {})} if (params or body) else {},
            )

        creds = self.decrypt_credentials(connection)
        headers = self._auth_headers(tool, creds)
        cleaned_base = _sanitize_url_string(tool.base_url or "")
        cleaned_endpoint = _normalize_endpoint(endpoint)
        if not cleaned_base.lower().startswith(("http://", "https://")):
            raise DynamicAgentError(
                f"Tool `{tool.name}` has an invalid base URL ({tool.base_url!r}). "
                "Re-fetch the docs from the Tools panel or set a seed for this tool."
            )
        url = cleaned_base.rstrip("/") + cleaned_endpoint

        try:
            resp = requests.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                json=body if body is not None else None,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise DynamicAgentError(f"HTTP request to {url} failed: {exc}") from exc

        ct = resp.headers.get("content-type", "")
        if "application/json" in ct:
            try:
                parsed: Any = resp.json()
            except ValueError:
                parsed = resp.text
        else:
            parsed = resp.text

        effective_status = _interpret_provider_level_error(tool, resp.status_code, parsed)

        connection.last_used_at = datetime.utcnow()
        return effective_status, parsed

    def _execute_boto3(
        self,
        *,
        tool: ToolDefinition,
        connection: DynamicToolConnection,
        endpoint: str,
        kwargs: Dict[str, Any],
    ) -> Tuple[int, Any]:
        try:
            import boto3
            from botocore.exceptions import (
                BotoCoreError,
                ClientError,
                NoCredentialsError,
            )
        except ImportError as exc:
            raise DynamicAgentError(
                "boto3 isn't installed — run `pip install boto3` to enable AWS."
            ) from exc

        creds = self.decrypt_credentials(connection)
        access_key = creds.get("access_key_id") or creds.get("aws_access_key_id")
        secret_key = creds.get("secret_access_key") or creds.get("aws_secret_access_key")
        region = (
            creds.get("region")
            or (tool.auth_config or {}).get("default_region")
            or "us-east-1"
        )
        if not (access_key and secret_key):
            raise DynamicAgentError(
                "AWS access_key_id / secret_access_key are missing from this "
                "connection — re-enter credentials."
            )

        path = (endpoint or "").lstrip("/")
        if "/" not in path:
            raise DynamicAgentError(
                f"AWS endpoint must be '<service>/<operation>', got {endpoint!r}. "
                "Example: 'ec2/describe_instances'."
            )
        service, operation = path.split("/", 1)
        service = service.strip().lower()
        operation = operation.strip()
        if not service or not operation:
            raise DynamicAgentError(
                f"AWS endpoint missing service or operation: {endpoint!r}"
            )

        try:
            client = boto3.client(
                service,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
        except Exception as exc:
            raise DynamicAgentError(
                f"Could not build boto3 client for service `{service}`: {exc}"
            ) from exc

        kwargs = _fixup_boto3_kwargs(service, operation, kwargs, region)

        method_fn = getattr(client, operation, None)
        if not callable(method_fn):
            available = [
                m for m in dir(client) if not m.startswith("_") and callable(getattr(client, m, None))
            ][:30]
            raise DynamicAgentError(
                f"boto3 `{service}` client has no operation `{operation}`. "
                f"A few real operations: {', '.join(available)}…"
            )

        try:
            response = method_fn(**(kwargs or {}))
        except NoCredentialsError as exc:
            connection.last_used_at = datetime.utcnow()
            return 401, {"error": str(exc)}
        except ClientError as exc:
            connection.last_used_at = datetime.utcnow()
            err_info = (exc.response or {}).get("Error") or {}
            meta = (exc.response or {}).get("ResponseMetadata") or {}
            return (
                int(meta.get("HTTPStatusCode") or 400),
                {
                    "error": err_info.get("Message") or str(exc),
                    "code": err_info.get("Code"),
                    "service": service,
                    "operation": operation,
                },
            )
        except BotoCoreError as exc:
            raise DynamicAgentError(f"boto3 error: {exc}") from exc

        if isinstance(response, dict):
            response = {k: v for k, v in response.items() if k != "ResponseMetadata"}
        connection.last_used_at = datetime.utcnow()
        return 200, response

    def _auth_headers(
        self, tool: ToolDefinition, creds: Dict[str, Any]
    ) -> Dict[str, str]:
        at = (tool.auth_type or "API_KEY").upper()
        cfg = tool.auth_config or {}
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "Adaptora-DynamicAgent/1.0",
        }
        for k, v in (cfg.get("extra_headers") or {}).items():
            headers[k] = v

        if at in ("API_KEY", "BEARER", "PAT"):
            secret = creds.get("secret") or creds.get("api_key") or creds.get("token")
            if secret:
                header_name = cfg.get("header_name") or "Authorization"
                prefix = cfg.get("credential_prefix")
                if prefix is None:
                    prefix = "Bearer " if at in ("BEARER", "PAT") else ""
                headers[header_name] = f"{prefix}{secret}"
        elif at == "BASIC":
            import base64

            u = creds.get("username") or ""
            p = creds.get("password") or ""
            token = base64.b64encode(f"{u}:{p}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        elif at in ("OAUTH2", "OAUTH2_PKCE"):
            token = creds.get("access_token")
            if token:
                header_name = cfg.get("header_name") or "Authorization"
                prefix = cfg.get("credential_prefix") or "Bearer "
                headers[header_name] = f"{prefix}{token}"
        return headers

    def refresh_oauth_token(
        self, db: Session, conn: DynamicToolConnection, tool: ToolDefinition
    ) -> bool:
        creds = self.decrypt_credentials(conn)
        refresh_token = creds.get("refresh_token")
        token_url = (tool.auth_config or {}).get("oauth_token_url")
        client_id = creds.get("client_id")
        client_secret = creds.get("client_secret")
        if not (refresh_token and token_url and client_id and client_secret):
            return False
        try:
            resp = requests.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
                timeout=20,
            )
            if resp.status_code >= 400:
                logger.warning(
                    f"oauth refresh for {tool.name} returned {resp.status_code}: "
                    f"{resp.text[:200]!r}"
                )
                return False
            body = resp.json()
        except Exception as exc:
            logger.warning(f"oauth refresh for {tool.name} failed: {exc}")
            return False

        new_access = body.get("access_token")
        if not new_access:
            return False
        creds["access_token"] = new_access
        if body.get("refresh_token"):
            creds["refresh_token"] = body["refresh_token"]
        expires_in = body.get("expires_in")
        conn.credentials_encrypted = encrypt_api_key(json.dumps(creds, default=str))
        conn.token_expires_at = (
            datetime.utcnow() + timedelta(seconds=int(expires_in))
            if expires_in
            else None
        )
        db.commit()
        return True

    def summarize_for_user(
        self,
        *,
        prompt: str,
        plan: Dict[str, Any],
        http_status: Optional[int],
        response_body: Any,
        error: Optional[str],
        language: str = "en",
    ) -> str:
        sys_prompt = (
            _SUMMARY_HINGLISH_SYSTEM if language == "hinglish" else _SUMMARY_EN_SYSTEM
        )
        if isinstance(response_body, (dict, list)):
            response_excerpt = json.dumps(response_body, default=str)[:1500]
        else:
            response_excerpt = (str(response_body or ""))[:1500]
        user_msg = (
            f"User prompt: {prompt!r}\n"
            f"Action taken: {plan.get('summary') or plan.get('method')} {plan.get('endpoint')}\n"
            f"HTTP status: {http_status}\n"
            f"Error: {error or 'none'}\n"
            f"Response excerpt:\n{response_excerpt}\n\n"
            "Write the user-facing one-paragraph summary now."
        )
        text = _ollama_chat_text(sys_prompt, user_msg, temperature=0.2, num_predict=220)
        return text.strip() or self._fallback_summary(
            language=language, http_status=http_status, error=error
        )

    @staticmethod
    def _fallback_summary(
        *, language: str, http_status: Optional[int], error: Optional[str]
    ) -> str:
        if error:
            if language == "hinglish":
                return f"Action fail ho gaya: {error}"
            return f"Action failed: {error}"
        if http_status is not None and http_status < 400:
            return "Done ✓" if language != "hinglish" else "Ho gaya ✓"
        return f"HTTP {http_status}" if http_status else "Unknown result"

    def run_turn(
        self,
        db: Session,
        *,
        user_id: int,
        prompt: str,
        language: str = "en",
        status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        if language not in ("en", "hinglish"):
            language = "en"

        def emit(step: str, **data: Any) -> None:
            if not status_callback:
                return
            try:
                status_callback(step, data)
            except Exception as exc:
                logger.warning(f"status_callback({step!r}) failed: {exc}")

        emit("identifying_tool", prompt=prompt)
        decision = self.identify_tool(prompt)
        tool_name = decision.get("tool")
        intent = decision.get("intent")
        emit(
            "tool_identified",
            tool=tool_name,
            intent=intent,
            confidence=decision.get("confidence"),
        )

        if not tool_name:
            return self._log_and_return(
                db,
                user_id=user_id,
                language=language,
                prompt=prompt,
                tool_name=None,
                thought=(
                    f"Could not identify a tool from the prompt "
                    f"(reason: {decision.get('reason')})."
                ),
                action="ask_user",
                action_input={"hint": "Tell me which tool to use."},
                status="error",
                summary=(
                    "Mujhe samajh nahi aaya konsa tool use karna hai. "
                    "Tool ka naam ya intent batayein."
                    if language == "hinglish"
                    else "I couldn't tell which tool you meant. "
                    "Try naming the tool (e.g. 'connect github')."
                ),
                started=started,
                final_answer=None,
            )

        emit("looking_up_docs", tool=tool_name)
        tool = self.lookup_or_fetch_docs(db, tool_name)
        if tool:
            emit(
                "docs_loaded",
                tool=tool.name,
                source=tool.source,
                endpoint_count=len(tool.endpoints or {}),
            )
        if not tool:
            return self._log_and_return(
                db,
                user_id=user_id,
                language=language,
                prompt=prompt,
                tool_name=tool_name,
                thought=(
                    f"Identified `{tool_name}`, but I couldn't find or fetch "
                    "its API docs. Without docs I can't plan a safe call."
                ),
                action="search_docs",
                action_input={"tool": tool_name, "status": "not_found"},
                status="needs_tool_setup",
                summary=(
                    f"`{tool_name}` ka API documentation nahi mil paya. "
                    "Manually setup karne ki zaroorat hai."
                    if language == "hinglish"
                    else f"I couldn't find docs for `{tool_name}`. "
                    "It may need manual setup."
                ),
                started=started,
                final_answer=None,
            )

        thought_id = (
            f"Tool identified: `{tool.name}` ({tool.auth_type}). Docs source: "
            f"`{tool.source}`. Base URL: {tool.base_url}."
        )

        emit("checking_connection", tool=tool.name)
        conn = self.load_connection(db, user_id, tool.name)
        if conn:
            emit("connection_found", tool=tool.name, auth_type=tool.auth_type)
        else:
            emit("connection_missing", tool=tool.name, auth_type=tool.auth_type)
        if not conn:
            return self._log_and_return(
                db,
                user_id=user_id,
                language=language,
                prompt=prompt,
                tool_name=tool.name,
                thought=(
                    f"{thought_id} No active credentials for this user — "
                    "must collect them before any call."
                ),
                action="ask_user_creds",
                action_input={
                    "tool": tool.name,
                    "display_name": tool.display_name,
                    "auth_type": tool.auth_type,
                    "credential_fields": self.required_credential_fields(tool, language),
                    "setup_instructions": self.setup_instructions(tool, language),
                    "docs_url": tool.docs_url,
                    "pat_create_url": (tool.auth_config or {}).get("pat_create_url"),
                },
                status="needs_credentials",
                summary=(
                    f"{tool.display_name} se connect karne ke liye credentials "
                    f"chahiye ({tool.auth_type})."
                    if language == "hinglish"
                    else f"To connect {tool.display_name} I need your "
                    f"credentials ({tool.auth_type})."
                ),
                started=started,
                final_answer=None,
            )

        if intent == "connect" or not self._prompt_describes_action(prompt):
            return self._log_and_return(
                db,
                user_id=user_id,
                language=language,
                prompt=prompt,
                tool_name=tool.name,
                thought=(
                    f"{thought_id} Connection already on file — nothing to "
                    "execute, just confirming."
                ),
                action="already_connected",
                action_input={"tool": tool.name},
                status="success",
                summary=(
                    f"{tool.display_name} pehle se connected hai. "
                    "Ab koi action prompt bhejo."
                    if language == "hinglish"
                    else f"{tool.display_name} is already connected. "
                    "Tell me what to do next."
                ),
                started=started,
                final_answer=None,
            )

        if (
            (tool.auth_type or "").upper() in ("OAUTH2", "OAUTH2_PKCE")
            and conn.token_expires_at
            and conn.token_expires_at <= datetime.utcnow() + timedelta(seconds=30)
        ):
            emit("refreshing_oauth_token", tool=tool.name)
            self.refresh_oauth_token(db, conn, tool)

        emit("planning_action", tool=tool.name)
        plan = self.plan_action(tool=tool, prompt=prompt)
        emit(
            "action_planned",
            method=(plan.get("method") or "").upper(),
            endpoint=plan.get("endpoint"),
            summary=plan.get("summary"),
        )
        method = (plan.get("method") or "").upper()
        endpoint = plan.get("endpoint")
        if not method or not endpoint or method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return self._log_and_return(
                db,
                user_id=user_id,
                language=language,
                prompt=prompt,
                tool_name=tool.name,
                thought=(
                    f"{thought_id} Planner could not produce a valid action: "
                    f"{plan.get('summary')}"
                ),
                action="plan_action",
                action_input=plan,
                status="error",
                summary=(
                    "Action plan banane mein problem aa gayi. Prompt ko thoda "
                    "specific karke try karo."
                    if language == "hinglish"
                    else "I couldn't build a valid action plan for this prompt. "
                    "Try being more specific."
                ),
                started=started,
                final_answer=None,
            )

        emit("executing", tool=tool.name, method=method, endpoint=endpoint)
        try:
            http_status, response_body = self.execute_http(
                tool=tool,
                connection=conn,
                method=method,
                endpoint=endpoint,
                params=plan.get("params"),
                body=plan.get("body"),
            )
            emit("executed", http_status=http_status)
            error_text = (
                None
                if http_status < 400
                else (
                    response_body
                    if isinstance(response_body, str)
                    else json.dumps(response_body, default=str)[:2000]
                )
            )
        except DynamicAgentError as exc:
            http_status = None
            response_body = None
            error_text = str(exc)

        status_label = (
            "success"
            if (http_status is not None and http_status < 400)
            else "error"
        )

        db.commit()

        emit("summarizing", status=("success" if (http_status is not None and http_status < 400) else "error"))
        summary = self.summarize_for_user(
            prompt=prompt,
            plan=plan,
            http_status=http_status,
            response_body=response_body,
            error=error_text,
            language=language,
        )

        return self._log_and_return(
            db,
            user_id=user_id,
            language=language,
            prompt=prompt,
            tool_name=tool.name,
            thought=(
                f"{thought_id} Plan: {method} {endpoint} — {plan.get('summary')}"
            ),
            action="execute_action",
            action_input={
                "method": method,
                "endpoint": endpoint,
                "params": plan.get("params"),
                "body": plan.get("body"),
            },
            status=status_label,
            summary=summary,
            started=started,
            final_answer=(
                summary
                if status_label == "success"
                else None
            ),
            http_status=http_status,
            response_body=response_body,
            error=error_text,
        )

    @staticmethod
    def _prompt_describes_action(prompt: str) -> bool:
        p = (prompt or "").lower()
        connect_only_phrases = ("connect", "setup", "set up", "add ", "link ", "integrate")
        action_verbs = (
            "send", "create", "make", "post", "list", "fetch", "get ", "show",
            "find", "search", "open", "close", "delete", "remove", "update",
            "edit", "comment", "merge", "assign", "schedule", "invite",
            "upload", "download",
        )
        if any(v in p for v in action_verbs):
            return True
        if any(p.startswith(v) or f" {v}" in p for v in connect_only_phrases):
            return False
        return True

    @staticmethod
    def _log_and_return(
        db: Session,
        *,
        user_id: int,
        language: str,
        prompt: str,
        tool_name: Optional[str],
        thought: str,
        action: str,
        action_input: Any,
        status: str,
        summary: str,
        started: float,
        final_answer: Optional[str],
        http_status: Optional[int] = None,
        response_body: Any = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        duration_ms = (time.perf_counter() - started) * 1000
        if isinstance(response_body, (dict, list)):
            serialized = json.dumps(response_body, default=str)[:50_000]
        else:
            serialized = (str(response_body) if response_body is not None else None)
            if serialized:
                serialized = serialized[:50_000]

        log = DynamicAgentRunLog(
            user_id=user_id,
            language=language,
            tool_name=tool_name,
            prompt=prompt,
            thought=thought,
            action=action,
            action_input=action_input,
            summary=summary,
            final_answer=final_answer,
            status=status,
            http_status=http_status,
            response_body=serialized,
            error=error,
            duration_ms=duration_ms,
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        return {
            "log_id": log.id,
            "status": status,
            "tool": tool_name,
            "thought": thought,
            "action": action,
            "action_input": action_input,
            "summary": summary,
            "final_answer": final_answer,
            "http_status": http_status,
            "response": response_body,
            "error": error,
            "duration_ms": duration_ms,
            "language": language,
        }

dynamic_agent_service = DynamicAgentService()
