"use client";

import React, { useEffect, useRef, useState } from "react";
import type {
  AgentArtifactAccess,
  AgentArtifactPurpose,
  AgentExternalVideoPart,
  AgentImagePart,
  AgentVideoPart,
} from "@zebra-agent/ui-contracts";

export type AgentArtifactResolver = (
  artifactId: string,
  purpose: AgentArtifactPurpose,
) => AgentArtifactAccess | Promise<AgentArtifactAccess>;

interface MediaBlockProps<TPart> {
  part: TPart;
  resolveArtifact?: AgentArtifactResolver;
  labels: AgentMediaLabels;
}

export interface AgentMediaLabels {
  close: string;
  failed: string;
  loading: string;
  openImage: string;
  unavailable: string;
  openExternalVideo?: string;
  playExternalVideo?: string;
}

export function AgentImageBlock({ labels, part, resolveArtifact }: MediaBlockProps<AgentImagePart>) {
  const sourceId = part.thumbnailArtifactId ?? part.artifactId;
  const thumbnail = useArtifactAccess(resolveArtifact, sourceId, "preview", part.state);
  const [open, setOpen] = useState(false);
  const openButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const full = useArtifactAccess(resolveArtifact, open ? part.artifactId : undefined, "preview", part.state);
  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
      if (event.key === "Tab") {
        event.preventDefault();
        closeButton.current?.focus();
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      openButton.current?.focus();
    };
  }, [open]);
  if (part.state === "processing" || thumbnail.status === "loading") {
    return <AgentMediaPlaceholder label={labels.loading} />;
  }
  if (part.state === "failed" || thumbnail.status === "failed" || !thumbnail.access) {
    return <AgentMediaPlaceholder failed label={labels.failed} />;
  }
  return (
    <figure className="zebra-agent-media zebra-agent-media--image">
      <button
        aria-label={labels.openImage}
        className="zebra-agent-media__image-button"
        onClick={() => setOpen(true)}
        ref={openButton}
        type="button"
      >
        <img
          alt={part.alt}
          decoding="async"
          height={part.height}
          loading="lazy"
          src={thumbnail.access.url}
          width={part.width}
        />
      </button>
      {part.fileName ? <figcaption>{part.fileName}</figcaption> : null}
      {open ? (
        <div aria-label={part.alt} aria-modal="true" className="zebra-agent-media-dialog" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }} role="dialog">
          <button aria-label={labels.close} className="zebra-agent-media-dialog__close" onClick={() => setOpen(false)} ref={closeButton} type="button">×</button>
          {full.access ? <img alt={part.alt} src={full.access.url} /> : <AgentMediaPlaceholder failed={full.status === "failed"} label={full.status === "failed" ? labels.failed : labels.loading} />}
        </div>
      ) : null}
    </figure>
  );
}

export function AgentVideoBlock({ labels, part, resolveArtifact }: MediaBlockProps<AgentVideoPart>) {
  const video = useArtifactAccess(resolveArtifact, part.artifactId, "preview", part.state);
  const poster = useArtifactAccess(resolveArtifact, part.posterArtifactId, "poster", part.state);
  const captions = useArtifactAccess(resolveArtifact, part.captionsArtifactId, "captions", part.state);
  if (part.state === "processing" || video.status === "loading") {
    return <AgentMediaPlaceholder label={labels.loading} />;
  }
  if (part.state === "failed" || video.status === "failed" || !video.access) {
    return <AgentMediaPlaceholder failed label={labels.failed} />;
  }
  return (
    <figure className="zebra-agent-media zebra-agent-media--video">
      <video
        controls
        height={part.height}
        playsInline
        poster={poster.access?.url}
        preload="metadata"
        width={part.width}
      >
        <source src={video.access.url} type={part.mimeType} />
        {captions.access ? <track default kind="captions" src={captions.access.url} srcLang={part.captionsLanguage ?? "und"} /> : null}
        {labels.unavailable}
      </video>
      <figcaption><strong>{part.title}</strong>{part.description ? <span>{part.description}</span> : null}</figcaption>
    </figure>
  );
}

function publicHttpsUrl(value: string): URL | undefined {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (url.protocol !== "https:" || url.username || url.password || url.port ||
        !host.includes(".") || host === "localhost" || host.endsWith(".localhost") ||
        host.endsWith(".local") || host.endsWith(".internal") ||
        /^[\d.]+$/.test(host) || host.includes(":")) return undefined;
    return url;
  } catch {
    return undefined;
  }
}

function externalVideoSource(part: AgentExternalVideoPart): { href: string; embed?: string; mimeType?: string } | undefined {
  const url = publicHttpsUrl(part.url);
  if (!url) return undefined;
  const host = url.hostname.toLowerCase();
  if (part.provider === "direct") {
    const match = /\.(mp4|webm)$/i.exec(url.pathname);
    return match ? { href: url.href, mimeType: `video/${match[1]!.toLowerCase()}` } : undefined;
  }
  if (part.provider === "website") return { href: url.href };
  if (part.provider === "youtube") {
    const id = host === "youtu.be" ? /^\/([\w-]{11})\/?$/.exec(url.pathname)?.[1]
      : ["youtube.com", "www.youtube.com", "m.youtube.com"].includes(host)
        ? url.pathname === "/watch" ? url.searchParams.get("v") : /^\/(?:shorts|embed)\/([\w-]{11})\/?$/.exec(url.pathname)?.[1]
        : undefined;
    if (!id || !/^[\w-]{11}$/.test(id)) return undefined;
    return { href: `https://www.youtube.com/watch?v=${id}`, embed: `https://www.youtube-nocookie.com/embed/${id}` };
  }
  if (part.provider === "vimeo") {
    const id = host === "vimeo.com" || host === "www.vimeo.com"
      ? /^\/(\d+)\/?$/.exec(url.pathname)?.[1]
      : host === "player.vimeo.com" ? /^\/video\/(\d+)\/?$/.exec(url.pathname)?.[1] : undefined;
    return id ? { href: `https://vimeo.com/${id}`, embed: `https://player.vimeo.com/video/${id}` } : undefined;
  }
  const id = ["bilibili.com", "www.bilibili.com", "m.bilibili.com"].includes(host)
    ? /^\/video\/(BV[0-9A-Za-z]{10})\/?$/.exec(url.pathname)?.[1] : undefined;
  return id ? { href: `https://www.bilibili.com/video/${id}`, embed: `https://player.bilibili.com/player.html?bvid=${id}` } : undefined;
}

export function AgentExternalVideoBlock({ labels, part }: { labels: AgentMediaLabels; part: AgentExternalVideoPart }) {
  const [play, setPlay] = useState(false);
  const [failed, setFailed] = useState(false);
  const [posterFailed, setPosterFailed] = useState(false);
  useEffect(() => { setPlay(false); setFailed(false); }, [part.provider, part.url]);
  useEffect(() => { setPosterFailed(false); }, [part.posterUrl]);
  const source = externalVideoSource(part);
  const poster = part.posterUrl ? publicHttpsUrl(part.posterUrl)?.href : undefined;
  if (part.state === "processing") return <AgentMediaPlaceholder label={labels.loading} />;
  if (!source) return <AgentMediaPlaceholder failed label={labels.unavailable} />;
  const fallback = <a href={source.href} rel="noopener noreferrer" target="_blank">{labels.openExternalVideo ?? "Open video"}</a>;
  return (
    <figure className="zebra-agent-media zebra-agent-media--external-video">
      {part.state === "ready" && !failed && source.mimeType ? (
        <video controls onError={() => setFailed(true)} playsInline poster={poster} preload="metadata">
          <source src={source.href} type={source.mimeType} />
          {labels.unavailable}
        </video>
      ) : part.state === "ready" && !failed && play && source.embed ? (
        <iframe allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; web-share" allowFullScreen onError={() => setFailed(true)} referrerPolicy="strict-origin-when-cross-origin" sandbox="allow-scripts allow-same-origin allow-presentation" src={source.embed} title={part.title} />
      ) : (
        <div className="zebra-agent-media__external-fallback">
          {poster && !posterFailed ? <img alt="" loading="lazy" onError={() => setPosterFailed(true)} referrerPolicy="no-referrer" src={poster} /> : null}
          {!poster || posterFailed ? <span className="zebra-agent-media__external-title">{part.title}</span> : null}
          {part.state === "ready" && !failed && source.embed ? <button onClick={() => setPlay(true)} type="button">{labels.playExternalVideo ?? "Play video"}</button> : null}
          {part.state === "failed" || failed ? <span role="status">{labels.unavailable}</span> : null}
        </div>
      )}
      <figcaption><strong>{part.title}</strong>{part.description ? <span>{part.description}</span> : null}{fallback}</figcaption>
    </figure>
  );
}

function AgentMediaPlaceholder({ failed = false, label }: { failed?: boolean; label: string }) {
  return <div className={`zebra-agent-media-placeholder ${failed ? "zebra-agent-media-placeholder--failed" : ""}`.trim()} role={failed ? "alert" : "status"}>{label}</div>;
}

type ArtifactAccessState =
  | { access?: undefined; status: "idle" | "loading" | "failed" }
  | { access: AgentArtifactAccess; status: "ready" };

export function useArtifactAccess(
  resolver: AgentArtifactResolver | undefined,
  artifactId: string | undefined,
  purpose: AgentArtifactPurpose,
  partState: "processing" | "ready" | "failed",
): ArtifactAccessState {
  const [state, setState] = useState<ArtifactAccessState>({ status: "idle" });
  useEffect(() => {
    if (!resolver || !artifactId || partState !== "ready") {
      setState({ status: "idle" });
      return;
    }
    let active = true;
    setState({ status: "loading" });
    void Promise.resolve(resolver(artifactId, purpose)).then(
      (access) => {
        if (active && access.artifactId === artifactId && access.url) {
          setState({ access, status: "ready" });
        } else if (active) {
          setState({ status: "failed" });
        }
      },
      () => {
        if (active) setState({ status: "failed" });
      },
    );
    return () => { active = false; };
  }, [artifactId, partState, purpose, resolver]);
  return state;
}
