-- Atelier: untrusted documents must not make pandoc embed local files or fetch URLs.
-- Images become their alt text (relative images can't resolve anyway: uploads are single files).
function Image(el)
  return el.caption
end
