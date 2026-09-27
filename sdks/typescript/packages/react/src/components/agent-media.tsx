"use client";

import React, { useEffect, useState } from "react";
import type {
  AgentArtifactAccess,
  AgentArtifactPurpose,
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
}

export function AgentImageBlock({ labels, part, resolveArtifact }: MediaBlockProps<AgentImagePart>) {
  const sourceId = part.thumbnailArtifactId ?? part.artifactId;
  const thumbnail = useArtifactAccess(resolveArtifact, sourceId, "preview", part.state);
  const [open, setOpen] = useState(false);
  const full = useArtifactAccess(resolveArtifact, open ? part.artifactId : undefined, "preview", part.state);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
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
        <div aria-label={part.alt} aria-modal="true" className="zebra-agent-media-dialog" role="dialog">
          <button aria-label={labels.close} className="zebra-agent-media-dialog__close" onClick={() => setOpen(false)} type="button">×</button>
          {full.access ? <img alt={part.alt} src={full.access.url} /> : <AgentMediaPlaceholder label={labels.loading} />}
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
        {captions.access ? <track default kind="captions" src={captions.access.url} srcLang="en" /> : null}
        {labels.unavailable}
      </video>
      <figcaption><strong>{part.title}</strong>{part.description ? <span>{part.description}</span> : null}</figcaption>
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
