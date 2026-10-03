import { cn } from "@/lib/utils";

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((n) => n[0])
    .join("")
    .toUpperCase();
}

const avatarColors = [
  "bg-background-accent-blue-bolder",
  "bg-background-accent-teal-bolder",
  "bg-background-accent-green-bolder",
  "bg-background-accent-orange-bolder",
  "bg-background-accent-red-bolder",
  "bg-background-accent-purple-bolder",
];

function avatarColor(seed: string) {
  const idx = seed.split("").reduce((a, c) => a + c.charCodeAt(0), 0) % avatarColors.length;
  return avatarColors[idx];
}

export function Avatar({
  name,
  size = 36,
  className,
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-semibold text-text-inverse",
        avatarColor(name),
        className,
      )}
      style={{ width: size, height: size, fontSize: size * 0.36 }}
    >
      {initials(name)}
    </div>
  );
}
