import type { Metadata } from 'next';

import { repository } from '@/lib/platform/repository';
import {
  ManifestEditor,
  ManifestNotFound
} from '@/features/integrations/components/manifest-editor';

export const metadata: Metadata = {
  title: 'Manifest 编辑器'
};

/** Backend Manifest 三栏编辑器页（PRD 12.4）。 */
export default async function ManifestEditorPage({
  params
}: {
  params: Promise<{ manifestId: string }>;
}) {
  const { manifestId } = await params;
  const manifest = repository.manifest(manifestId);

  if (!manifest) {
    return <ManifestNotFound manifestId={manifestId} />;
  }

  return <ManifestEditor manifest={manifest} />;
}
