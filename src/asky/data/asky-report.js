/*****************************************************************************
 * casual-markdown - a lightweight regexp-base markdown parser
 * Copyright (c) 2022, Casualwriter (MIT Licensed)
 * https://github.com/casualwriter/casual-markdown
 *****************************************************************************/
var md = {
  yaml: {},
  before: function (str) {
    return str;
  },
  after: function (str) {
    return str;
  },
};
md.formatTag = function (html) {
  return html.replace(/</g, "&lt;").replace(/\>/g, "&gt;");
};
md.formatCode = function (match, title, block) {
  block = block.replace(/</g, "&lt;").replace(/\>/g, "&gt;");
  block = block.replace(/\t/g, "   ");
  return '<pre title="' + title + '"><code>' + block + "</code></pre>";
};
md.parser = function (mdstr) {
  mdstr = mdstr.replace(
    /\n(.+?)\n.*?\-\-\|\-\-.*?\n([\s\S]*?)\n\s*?\n/g,
    function (m, p1, p2) {
      var thead = p1
        .replace(/^\|(.+)/gm, "$1")
        .replace(/(.+)\|$/gm, "$1")
        .replace(/\|/g, "<th>");
      var tbody = p2
        .replace(/^\|(.+)/gm, "$1")
        .replace(/(.+)\|$/gm, "$1");
      tbody = tbody
        .replace(/(.+)/gm, "<tr><td>$1</td></tr>")
        .replace(/\|/g, "<td>");
      return (
        "\n<table>\n<thead>\n<tr><th>" +
        thead +
        "</th></tr>\n</thead>\n<tbody>" +
        tbody +
        "\n</tbody></table>\n\n"
      );
    },
  );
  mdstr = mdstr.replace(/^-{3,}|^\_{3,}|^\*{3,}$/gm, "<hr>");
  mdstr = mdstr
    .replace(/^##### (.*?)\s*#*$/gm, "<h5>$1</h5>")
    .replace(/^#### (.*?)\s*#*$/gm, "<h4>$1</h4>")
    .replace(/^### (.*?)\s*#*$/gm, "<h3>$1</h3>")
    .replace(/^## (.*?)\s*#*$/gm, "<h2>$1</h2>")
    .replace(/^# (.*?)\s*#*$/gm, "<h1>$1</h1>");
  mdstr = mdstr.replace(/``(.*?)``/gm, function (m, p) {
    return "<code>" + md.formatTag(p).replace(/`/g, "&#96;") + "</code>";
  });
  mdstr = mdstr.replace(/`(.*?)`/gm, "<code>$1</code>");
  mdstr = mdstr.replace(
    /^\>\> (.*$)/gm,
    "<blockquote><blockquote>$1</blockquote></blockquote>",
  );
  mdstr = mdstr.replace(/^\> (.*$)/gm, "<blockquote>$1</blockquote>");
  mdstr = mdstr.replace(
    /!\[(.*?)\]\((.*?) "(.*?)"\)/gm,
    '<img alt="$1" src="$2" $3 />',
  );
  mdstr = mdstr.replace(
    /!\[(.*?)\]\((.*?)\)/gm,
    '<img alt="$1" src="$2" />',
  );
  mdstr = mdstr.replace(
    /\[(.*?)\]\((.*?) "new"\)/gm,
    '<a href="$2" target=_new>$1</a>',
  );
  mdstr = mdstr.replace(
    /\[(.*?)\]\((.*?) "(.*?)"\)/gm,
    '<a href="$2" title="$3">$1</a>',
  );
  mdstr = mdstr.replace(
    /([<\s])(https?\:\/\/.*?)([\s\>])/gm,
    '$1<a href="$2">$2</a>$3',
  );
  mdstr = mdstr.replace(/\[(.*?)\]\((.*?)\)/gm, '<a href="$2">$1</a>');
  mdstr = mdstr.replace(/^[\*+-][ .](.*)/gm, "<ul><li>$1</li></ul>");
  mdstr = mdstr.replace(/^\d[ .](.*)/gm, "<ol><li>$1</li></ol>");
  mdstr = mdstr.replace(
    /^\s{2,6}[\*+-][ .](.*)/gm,
    "<ul><ul><li>$1</li></ul></ul>",
  );
  mdstr = mdstr.replace(
    /^\s{2,6}\d[ .](.*)/gm,
    "<ul><ol><li>$1</li></ol></ul>",
  );
  var oldStr;
  do {
    oldStr = mdstr;
    mdstr = mdstr.replace(/<\/ul>\n<ul>/g, "\n");
    mdstr = mdstr.replace(/<\/ol>\n<ol>/g, "\n");
    mdstr = mdstr.replace(/<\/ul><\/ul>\n<ul><ul>/g, "</ul>\n<ul>");
    mdstr = mdstr.replace(/<\/ul>\n<ul><ul>/g, "\n<ul>");
    mdstr = mdstr.replace(/<\/ul><\/ul>\n<ul>/g, "</ul>\n");
  } while (oldStr !== mdstr);
  mdstr = mdstr.replace(
    /\*\*\*(\w.*?[^\\])\*\*\*/gm,
    "<b><em>$1</em></b>",
  );
  mdstr = mdstr.replace(/\*\*(\w.*?[^\\])\*\*/gm, "<b>$1</b>");
  mdstr = mdstr.replace(/\*(\w.*?[^\\])\*/gm, "<em>$1</em>");
  mdstr = mdstr.replace(/___(\ w.*?[^\\])___/gm, "<b><em>$1</em></b>");
  mdstr = mdstr.replace(/__(\w.*?[^\\])__/gm, "<u>$1</u>");
  mdstr = mdstr.replace(/\^\^(\w.*?)\^\^/gm, "<ins>$1</ins>");
  mdstr = mdstr.replace(/~~(\w.*?)~~/gm, "<del>$1</del>");
  mdstr = mdstr
    .replace(/  \n/g, "\n<br/>")
    .replace(/\n\s*\n/g, "\n<p>\n");
  return mdstr.replace(/\\([`_~\*\+\-\.\^\\\<\>\(\)\[\]])/gm, "$1");
};
md.html = function (mdText) {
  mdText = mdText.replace(/\r\n/g, "\n");
  mdText = mdText
    .replace(/\n~~~/g, "\n```")
    .replace(/\n``` *(.*?)\n([\s\S]*?)\n``` *\n/g, md.formatCode);
  var pos1 = 0,
    pos2 = 0,
    mdHTML = "";
  while ((pos1 = mdText.indexOf("<code>")) >= 0) {
    pos2 = mdText.indexOf("</code>", pos1);
    mdHTML += md.parser(mdText.substr(0, pos1));
    mdHTML += mdText.substr(
      pos1,
      pos2 > 0 ? pos2 - pos1 + 7 : mdText.length,
    );
    mdText = mdText.substr(pos2 + 7);
  }
  return '<div class="markdown">' + mdHTML + md.parser(mdText) + "</div>";
};

document.getElementById("content").innerHTML = md.html(rawContent);
