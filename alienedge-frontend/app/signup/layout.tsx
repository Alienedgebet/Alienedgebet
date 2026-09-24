import { preload } from "react-dom";

const alienImageSrcSet = "/hero-alien-mascot-login-v1-540.webp 540w, /hero-alien-mascot-login-v1-1024.webp 1024w";
const alienImageSizes = "(max-width: 800px) 78vw, (max-width: 1100px) 49vw, 34vw";
export default function AuthLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  preload("/hero-alien-mascot-login-v1-1024.webp", {
    as: "image",
    fetchPriority: "high",
    imageSrcSet: alienImageSrcSet,
    imageSizes: alienImageSizes,
  });
  return children;
}