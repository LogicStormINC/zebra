"use client";

import React, { useState } from "react";
import type { AgentExternalVideoPart } from "@zebra-agent/ui-contracts";

export type ExternalVideoTarget =
  | { kind: "embed" | "file" | "link"; url: string }
  | null;

/** Build embed URLs ourselves. Never render an iframe from an arbitrary tool URL. */
export function resolveExternalVideo(sourceUrl: string): ExternalVideoTarget {
  if (sourceUrl.length > 2048) return null;
  let url: URL;
  try { url = new URL(sourceUrl); } catch { return null; }
  const host = url.hostname.toLowerCase();
  if (url.protocol !== "https:" || url.username || url.password || url.port || !host.includes(".")
    || host === "localhost" || /^(?:\d+\.){3}\d+$/.test(host) || host.includes(":")
    || host.endsWith(".local") || host.endsWith(".internal")) return null;
  const path = url.pathname;
  const youtubeId = host === "youtu.be" ? path.match(/^\/([\w-]{11})\/?$/)?.[1]
    : ["youtube.com", "www.youtube.com", "m.youtube.com"].includes(host)
      ? path === "/watch" ? url.searchParams.get("v") : path.match(/^\/(?:shorts|live|embed)\/([\w-]{11})\/?$/)?.[1]
      : null;
  if (youtubeId && /^[\w-]{11}$/.test(youtubeId))
    return { kind: "embed", url: `https://www.youtube-nocookie.com/embed/${youtubeId}` };
  if (["bilibili.com", "www.bilibili.com", "m.bilibili.com"].includes(host)) {
    const bvid = path.match(/^\/video\/(BV[\da-zA-Z]{10})(?:\/|$)/)?.[1];
    if (bvid) return { kind: "embed", url: `https://player.bilibili.com/player.html?bvid=${bvid}` };
  }
  if (host === "player.bilibili.com" && path === "/player.html") {
    const bvid = url.searchParams.get("bvid");
    if (bvid && /^BV[\da-zA-Z]{10}$/.test(bvid))
      return { kind: "embed", url: `https://player.bilibili.com/player.html?bvid=${bvid}` };
  }
  if (["vimeo.com", "www.vimeo.com", "player.vimeo.com"].includes(host)) {
    const id = path.match(/^\/(?:video\/)?(\d+)(?:\/|$)/)?.[1];
    if (id) return { kind: "embed", url: `https://player.vimeo.com/video/${id}` };
  }
  if (/\.(?:mp4|webm|ogv)$/i.test(path)) return { kind: "file", url: url.href };
  return { kind: "link", url: url.href };
}

export function AgentExternalVideoBlock({ part }: { part: AgentExternalVideoPart }) {
  const [opened, setOpened] = useState(false);
  const target = resolveExternalVideo(part.sourceUrl);
  if (part.state === "failed" || !target) return <div className="zebra-agent-media-placeholder zebra-agent-media-placeholder--failed" role="alert">Video link unavailable</div>;
  if (part.state === "processing") return <div className="zebra-agent-media-placeholder" role="status">Loading video</div>;
  return <figure className="zebra-agent-external-video">
    {opened && target.kind === "embed" ? <iframe allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowFullScreen loading="lazy" referrerPolicy="no-referrer" src={target.url} title={part.title} /> : null}
    {opened && target.kind === "file" ? <video autoPlay controls playsInline preload="metadata" src={target.url} /> : null}
    {!opened && target.kind !== "link" ? <button className="zebra-agent-external-video__play" onClick={() => setOpened(true)} type="button" aria-label={`Play ${part.title}`}><span aria-hidden="true">▶</span><strong>{part.title}</strong></button> : null}
    {target.kind === "link" ? <a className="zebra-agent-external-video__link" href={target.url} rel="noopener noreferrer" target="_blank"><span aria-hidden="true">▶</span><strong>{part.title}</strong><small>Open on source site ↗</small></a> : null}
    <figcaption>{part.description ? <span>{part.description}</span> : null}<a href={target.kind === "link" ? target.url : part.sourceUrl} rel="noopener noreferrer" target="_blank">Open original ↗</a></figcaption>
  </figure>;
}
