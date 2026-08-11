export function shouldOpenMetaAfterSignIn({
  event,
  bootstrapCompleted,
  knownUserId,
  nextUserId,
}: {
  event: string;
  bootstrapCompleted: boolean;
  knownUserId: string | null;
  nextUserId: string | null;
}): boolean {
  return event === "SIGNED_IN" && bootstrapCompleted && Boolean(nextUserId) && knownUserId !== nextUserId;
}
