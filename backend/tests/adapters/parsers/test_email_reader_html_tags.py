"""Email reader: HTML turned into text without letting one tag hold the memory.

``html.parser`` matches a whole tag with one regular expression whose backtracking state grows with
the tag's attributes, about 350 bytes for each one: a 1 MB email whose HTML is ``<a b b b ...>``
(500,000 attributes in one tag) peaked at 346 MB, 324 times the file, and one unclosed tag of
``b="`` repeated added about 200 MB. ``MAX_HTML_CHARS`` bounds the time, not that memory. The regex
runs before any attribute is built, so skipping the attributes would not help: a tag is now shown to
the parser ``MAX_TAG_CHARS`` at a time. The text of a normal HTML body is what it was: the ``GOLDEN``
outputs below were recorded from the code before the change, and the tests also compare against the
stock ``html.parser`` tag methods.
"""

from __future__ import annotations

import random
import time
import tracemalloc
from email.message import EmailMessage
from html.parser import HTMLParser

import pytest

from backend.app.adapters.parsers import email_reader
from backend.app.adapters.parsers.email_reader import html_to_text, read_eml
from backend.tests.adapters.parsers._timing import budget


def _eml(html: str) -> bytes:
    message = EmailMessage()
    message["From"] = "Acme Gas <billing@acme.example>"
    message["To"] = "ap@client.example"
    message["Subject"] = "Your February bill"
    message.set_content(html, subtype="html", cte="8bit")
    return message.as_bytes()


# --- bodies read as before ---------------------------------------------------------------------
# From the other email reader tests, word for word.
EXISTING = {
    "usage_line": "<p>Total Usage: <b>120</b> therms</p>",
    "table_bill": (
        "<html><head><title>Bill</title><style>td { color: red }</style></head><body>"
        "<h1>Acme&nbsp;Gas</h1><p>Account   1234<br>Service period: 01/01/2025 - 01/31/2025</p>"
        "<table><tr><th>Item</th><th>Amount</th></tr><tr><td>Total Usage</td><td>1,234 therms</td></tr>"
        "<tr><td>Amount due</td><td>&#36;98.10</td></tr></table>"
        "<script>document.write('hidden')</script><img src='https://tracker.example/pixel.png'></body></html>"
    ),
    "invoice_attached": "<p>Invoice attached.</p>",
    "see_invoice": "<p>Please see the attached invoice.</p>",
    "this_one": "<p>this one</p>",
    "kwh": "<p>Total <b>120</b> kWh</p>",
    "unclosed_title_in_head": "<head><title>x",
    "unclosed_title_before_body": "<title>Subject<body><p>Hello</p>",
    "nested_divs_and_pre": "<div>a<div>b</div></div><pre>1  2</pre>",
}

ELECTRIC_BILL = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Your Northwind Power bill</title>
<style type="text/css">
  body { margin: 0; padding: 0; font-family: Arial, sans-serif; }
  td > a { color: #0b5cad; }
  @media only screen and (max-width: 480px) { .wrap { width: 100% !important; } }
</style>
<!--[if mso]><style>table { border-collapse: collapse; }</style><![endif]-->
</head>
<body style="margin:0;padding:0;background:#f4f4f4;">
<span style="display:none;font-size:1px;color:#f4f4f4;">Your statement for February is ready</span>
<table role="presentation" class="wrap" width="600" cellpadding="0" cellspacing="0" border="0" align="center" bgcolor="#ffffff">
  <tr>
    <td style="padding:16px 24px;" align="left"><img src="https://cdn.northwind.example/logo.png" width="140" height="36" alt="Northwind Power" style="display:block;border:0;" /></td>
    <td style="padding:16px 24px;" align="right"><a href="https://my.northwind.example/account?acct=0044-1129&amp;utm_source=bill&amp;utm_medium=email" target="_blank">View online</a></td>
  </tr>
  <tr><td colspan="2" style="padding:0 24px;"><h1 style="font-size:22px;margin:0;">Your February statement</h1></td></tr>
  <tr>
    <td colspan="2" style="padding:8px 24px;">
      <p style="margin:0 0 8px 0;">Account number: <strong>0044-1129-77</strong><br />
      Service address: 18 Harbor Street, Unit 4B, Springfield<br />
      Billing period: Jan 14, 2025 &ndash; Feb 12, 2025 (29 days)</p>
    </td>
  </tr>
  <tr>
    <td colspan="2" style="padding:8px 24px;">
      <table role="presentation" width="100%" cellpadding="6" cellspacing="0" border="0">
        <thead>
          <tr bgcolor="#eeeeee"><th align="left">Charge</th><th align="right">Usage</th><th align="right">Amount</th></tr>
        </thead>
        <tbody>
          <tr><td>Previous balance</td><td align="right">&nbsp;</td><td align="right">$212.40</td></tr>
          <tr><td>Payment received - thank you</td><td align="right">&nbsp;</td><td align="right">-$212.40</td></tr>
          <tr><td>Customer charge</td><td align="right">29 days</td><td align="right">$11.60</td></tr>
          <tr><td>Energy charge, first 500 kWh</td><td align="right">500 kWh</td><td align="right">$61.25</td></tr>
          <tr><td>Energy charge, over 500 kWh</td><td align="right">318 kWh</td><td align="right">$48.07</td></tr>
          <tr><td>Fuel adjustment</td><td align="right">818 kWh</td><td align="right">$9.82</td></tr>
          <tr><td>Franchise fee &amp; sales tax</td><td align="right">&nbsp;</td><td align="right">$7.31</td></tr>
          <tr bgcolor="#fafafa"><td><b>Total amount due</b></td><td align="right">818 kWh</td><td align="right"><b>$138.05</b></td></tr>
        </tbody>
      </table>
    </td>
  </tr>
  <tr>
    <td colspan="2" style="padding:12px 24px;">
      <p>Pay by <b>March 7, 2025</b> to avoid a late fee of 1.5%.</p>
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td bgcolor="#0b5cad" style="padding:10px 20px;"><a href="https://pay.northwind.example/p/8Fk2LQ0z?src=email&amp;amt=138.05" style="color:#ffffff;text-decoration:none;">Pay $138.05 now</a></td></tr></table>
    </td>
  </tr>
  <tr>
    <td colspan="2" style="padding:12px 24px;font-size:12px;color:#666666;">
      <p>Questions? Call 1-800-555-0143 or reply to this email.<br />
      <a href="https://www.northwind.example/privacy">Privacy</a> | <a href="https://www.northwind.example/terms">Terms</a> | <a href="https://www.northwind.example/unsubscribe?u=0044">Unsubscribe</a></p>
      <small>Northwind Power Co., 500 Grid Road, Springfield. Meter 7731-A read on Feb 12.</small>
    </td>
  </tr>
</table>
<img src="https://track.northwind.example/o.gif?id=991" width="1" height="1" alt="" />
</body>
</html>
"""

GAS_BILL = """<html>
<body bgcolor=white text=black link=blue>
<center><font face="Arial" size=4><b>Lakeview Gas &amp; Heating</b></font><br>
<font size=2>Statement date: 02/14/2025 &nbsp;&nbsp; Page 1 of 2</font></center>
<hr>
<table border=1 cellspacing=0 cellpadding=4 width=100%>
<tr><td><b>Account</b></td><td>55-20931-004</td><td><b>Rate class</b></td><td>RES-1 Residential Heating</td></tr>
<tr><td><b>Meter</b></td><td>GM-88213</td><td><b>Service</b></td><td>22 Orchard Lane</td></tr>
</table>
<p>
<b>Meter readings</b>
<pre>
  Previous read (01/15/2025):    41,882 ccf
  Current read  (02/13/2025):    42,317 ccf
  Usage:                            435 ccf  x  1.0371 therm factor = 451 therms
</pre>
<table width=100% cellpadding=3>
<tr><th align=left>Description<th align=right>Quantity<th align=right>Rate<th align=right>Amount
<tr><td>Basic service charge<td align=right>1<td align=right>$14.00<td align=right>$14.00
<tr><td>Delivery, first 50 therms<td align=right>50<td align=right>$0.4410<td align=right>$22.05
<tr><td>Delivery, next 401 therms<td align=right>401<td align=right>$0.2985<td align=right>$119.70
<tr><td>Gas supply cost<td align=right>451<td align=right>$0.5120<td align=right>$230.91
<tr><td>Weather normalization<td align=right>&nbsp;<td align=right>&nbsp;<td align=right>-$6.12
<tr><td colspan=3><b>Current charges</b><td align=right><b>$380.54</b>
</table>
<ul>
<li>Average daily use: 15.0 therms
<li>Same period last year: 402 therms
<li>Heating degree days: 1,104
</ul>
<p>See <a href="http://www.lakeviewgas.example/help/read-your-bill">how to read your bill</a> or <a href="mailto:care@lakeviewgas.example?subject=Account%2055-20931-004">email customer care</a>.
<!-- internal: template v7, do not edit -->
<script type="text/javascript">var _gaq = _gaq || []; _gaq.push(['_trackPageview']);</script>
</body>
</html>
"""

WATER_BILL = """<html><head>
<meta charset="utf-8">
<title>Lakeside Water District - Invoice 2025-0231</title>
<style>.num { text-align: right; } .muted { color: #777; }</style>
</head>
<body>
<div class="header">
  <h2>Lakeside Water District</h2>
  <p class="muted">Invoice <span id="inv">2025-0231</span> &middot; Issued Feb 3, 2025 &middot; Due Feb 28, 2025</p>
</div>
<dl>
  <dt>Customer</dt><dd>Harbor Street Condominium Association</dd>
  <dt>Service address</dt><dd>18 Harbor Street</dd>
  <dt>Account</dt><dd>WD-3318-02</dd>
</dl>
<table border="1" cellspacing="0" cellpadding="5">
  <thead>
    <tr><th colspan="2">Period</th><th>Water (gal)</th><th>Sewer (gal)</th><th>Charge</th></tr>
  </thead>
  <tbody>
    <tr><td>Dec 2024</td><td>12/03 - 01/02</td><td class="num">41,200</td><td class="num">38,900</td><td class="num">$286.44</td></tr>
    <tr><td>Jan 2025</td><td>01/03 - 02/02</td><td class="num">44,750</td><td class="num">40,100</td><td class="num">$301.18</td></tr>
    <tr><td colspan="4"><i>Stormwater fee (flat)</i></td><td class="num">$18.00</td></tr>
    <tr><td colspan="4"><i>Late fee waived</i></td><td class="num">$0.00</td></tr>
    <tr><td colspan="4"><strong>Total</strong></td><td class="num"><strong>$605.62</strong></td></tr>
  </tbody>
</table>
<p>Pay online at <a href="https://billpay.lakesidewater.example/pay?inv=2025-0231&acct=WD-3318-02&token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJXRC0zMzE4LTAyIiwiaW52IjoiMjAyNS0wMjMxIiwiZXhwIjoxNzQwNzg3MjAwfQ.Zm9vYmFyYmF6cXV4c29tZXNpZ25hdHVyZXZhbHVl&utm_campaign=feb&utm_content=paylink">billpay.lakesidewater.example</a>.</p>
<p>Usage this year vs. last year:</p>
<ol>
  <li>Dec: 41,200 vs 39,880</li>
  <li>Jan: 44,750 vs 42,010</li>
</ol>
<blockquote>Tip: a dripping tap wastes up to 3,000 gallons a year.</blockquote>
<address>Lakeside Water District<br>9 Spring Street<br>Springfield</address>
<noscript>Enable JavaScript to pay online.</noscript>
</body></html>
"""

WORD_BILL = """<html xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">
<head>
<meta http-equiv=Content-Type content="text/html; charset=us-ascii">
<meta name=Generator content="Microsoft Word 15 (filtered medium)">
<!--[if gte mso 9]><xml><o:OfficeDocumentSettings><o:AllowPNG/></o:OfficeDocumentSettings></xml><![endif]-->
<style><!--
p.MsoNormal, li.MsoNormal { margin:0in; font-size:11.0pt; font-family:"Calibri",sans-serif; }
--></style>
</head>
<body lang=EN-US link="#0563C1" vlink="#954F72">
<div class=WordSection1>
<p class=MsoNormal>Hello AP team,<o:p></o:p></p>
<p class=MsoNormal><o:p>&nbsp;</o:p></p>
<p class=MsoNormal>Please find our fleet fuel summary for <b>January 2025</b> below.<o:p></o:p></p>
<p class=MsoNormal><o:p>&nbsp;</o:p></p>
<TABLE class=MsoNormalTable border=0 cellspacing=0 cellpadding=0 width=480>
<TR><TD width=240 valign=top><p class=MsoNormal><b>Vehicle<o:p></o:p></b></p></TD><TD width=120 valign=top><p class=MsoNormal align=right><b>Gallons<o:p></o:p></b></p></TD><TD width=120 valign=top><p class=MsoNormal align=right><b>Cost<o:p></o:p></b></p></TD></TR>
<TR><TD valign=top><p class=MsoNormal>Truck 12 (diesel)<o:p></o:p></p></TD><TD valign=top><p class=MsoNormal align=right>212.4<o:p></o:p></p></TD><TD valign=top><p class=MsoNormal align=right>$801.55<o:p></o:p></p></TD></TR>
<TR><TD valign=top><p class=MsoNormal>Van 04 (gasoline)<o:p></o:p></p></TD><TD valign=top><p class=MsoNormal align=right>96.0<o:p></o:p></p></TD><TD valign=top><p class=MsoNormal align=right>$301.20<o:p></o:p></p></TD></TR>
</TABLE>
<p class=MsoNormal><o:p>&nbsp;</o:p></p>
<![if !supportLists]><![endif]>
<p class=MsoListParagraph style='margin-left:.5in;text-indent:-.25in'><![if !supportLists]><span style='font-family:Symbol'>&middot;<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp; </span></span><![endif]>Card 9921 statement attached<o:p></o:p></p>
<p class=MsoNormal>Thanks,<br>Dana<o:p></o:p></p>
</div>
</body>
</html>
"""

# A bill with a long tracking link and an image kept inside the message as a data: URI. Both tags
# are longer than a tag window (MAX_TAG_CHARS) and must read as the shorter ones do.
EMBEDDED_IMAGE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg" * 200
LONG_LINK = "https://click.northwind.example/r?u=" + "%2Fpay%3Fa%3D1%26b%3D2" * 600 + "&sig=Zm9v"
LONG_TAGS_BILL = (
    "<html><body><table><tr><td><img src=\"data:image/png;base64," + EMBEDDED_IMAGE + "\" alt=\"Northwind\" "
    "width=\"140\" height=\"36\"></td><td>Statement</td></tr>"
    "<tr><td>Amount due</td><td><a href=\"" + LONG_LINK + "\" target=\"_blank\" style=\"color:#0b5cad\">$138.05</a>"
    "</td></tr><tr><td>Due date</td><td>March 7, 2025</td></tr></table>"
    "<p>Thank you for your business.</p></body></html>"
)

BILLS = {
    "electric_bill": ELECTRIC_BILL,
    "gas_bill": GAS_BILL,
    "water_bill": WATER_BILL,
    "word_bill": WORD_BILL,
    "long_tags_bill": LONG_TAGS_BILL,
}
CORPUS = {**EXISTING, **BILLS}

# What html_to_text gave each body before the change (recorded from the code as it was).
GOLDEN: dict[str, str] = {
    "usage_line": "Total Usage: 120 therms",
    "table_bill": (
        "Acme Gas\n"
        "Account 1234\n"
        "Service period: 01/01/2025 - 01/31/2025\n"
        "Item\tAmount\n"
        "Total Usage\t1,234 therms\n"
        "Amount due\t$98.10"
    ),
    "invoice_attached": "Invoice attached.",
    "see_invoice": "Please see the attached invoice.",
    "this_one": "this one",
    "kwh": "Total 120 kWh",
    "unclosed_title_in_head": "",
    "unclosed_title_before_body": "Hello",
    "nested_divs_and_pre": (
        "a\n"
        "b\n"
        "1 2"
    ),
    "electric_bill": (
        "Your statement for February is ready\n"
        "View online\n"
        "Your February statement\n"
        "Account number: 0044-1129-77\n"
        "Service address: 18 Harbor Street, Unit 4B, Springfield\n"
        "Billing period: Jan 14, 2025 – Feb 12, 2025 (29 days)\n"
        "Charge\tUsage\tAmount\n"
        "Previous balance\t$212.40\n"
        "Payment received - thank you\t-$212.40\n"
        "Customer charge\t29 days\t$11.60\n"
        "Energy charge, first 500 kWh\t500 kWh\t$61.25\n"
        "Energy charge, over 500 kWh\t318 kWh\t$48.07\n"
        "Fuel adjustment\t818 kWh\t$9.82\n"
        "Franchise fee & sales tax\t$7.31\n"
        "Total amount due\t818 kWh\t$138.05\n"
        "Pay by March 7, 2025 to avoid a late fee of 1.5%.\n"
        "Pay $138.05 now\n"
        "Questions? Call 1-800-555-0143 or reply to this email.\n"
        "Privacy | Terms | Unsubscribe\n"
        "Northwind Power Co., 500 Grid Road, Springfield. Meter 7731-A read on Feb 12."
    ),
    "gas_bill": (
        "Lakeview Gas & Heating\n"
        "Statement date: 02/14/2025 Page 1 of 2\n"
        "Account\t55-20931-004\tRate class\tRES-1 Residential Heating\n"
        "Meter\tGM-88213\tService\t22 Orchard Lane\n"
        "Meter readings\n"
        "Previous read (01/15/2025): 41,882 ccf\n"
        "Current read (02/13/2025): 42,317 ccf\n"
        "Usage: 435 ccf x 1.0371 therm factor = 451 therms\n"
        "Description\tQuantity\tRate\tAmount\n"
        "Basic service charge\t1\t$14.00\t$14.00\n"
        "Delivery, first 50 therms\t50\t$0.4410\t$22.05\n"
        "Delivery, next 401 therms\t401\t$0.2985\t$119.70\n"
        "Gas supply cost\t451\t$0.5120\t$230.91\n"
        "Weather normalization\t-$6.12\n"
        "Current charges\t$380.54\n"
        "Average daily use: 15.0 therms\n"
        "Same period last year: 402 therms\n"
        "Heating degree days: 1,104\n"
        "See how to read your bill or email customer care."
    ),
    "water_bill": (
        "Lakeside Water District\n"
        "Invoice 2025-0231 · Issued Feb 3, 2025 · Due Feb 28, 2025\n"
        "Customer\n"
        "Harbor Street Condominium Association\n"
        "Service address\n"
        "18 Harbor Street\n"
        "Account\n"
        "WD-3318-02\n"
        "Period\tWater (gal)\tSewer (gal)\tCharge\n"
        "Dec 2024\t12/03 - 01/02\t41,200\t38,900\t$286.44\n"
        "Jan 2025\t01/03 - 02/02\t44,750\t40,100\t$301.18\n"
        "Stormwater fee (flat)\t$18.00\n"
        "Late fee waived\t$0.00\n"
        "Total\t$605.62\n"
        "Pay online at billpay.lakesidewater.example.\n"
        "Usage this year vs. last year:\n"
        "Dec: 41,200 vs 39,880\n"
        "Jan: 44,750 vs 42,010\n"
        "Tip: a dripping tap wastes up to 3,000 gallons a year.\n"
        "Lakeside Water District\n"
        "9 Spring Street\n"
        "Springfield"
    ),
    "word_bill": (
        "Hello AP team,\n"
        "Please find our fleet fuel summary for January 2025 below.\n"
        "Vehicle\n"
        "Gallons\n"
        "Cost\n"
        "Truck 12 (diesel)\n"
        "212.4\n"
        "$801.55\n"
        "Van 04 (gasoline)\n"
        "96.0\n"
        "$301.20\n"
        "· Card 9921 statement attached\n"
        "Thanks,\n"
        "Dana"
    ),
    "long_tags_bill": (
        "Statement\n"
        "Amount due\t$138.05\n"
        "Due date\tMarch 7, 2025\n"
        "Thank you for your business."
    ),
}


@pytest.mark.parametrize("name", list(CORPUS))
def test_a_normal_html_body_reads_exactly_as_before(name: str) -> None:
    assert html_to_text(CORPUS[name]) == GOLDEN[name]


# --- the same text as the stock html.parser tag methods gave ---------------------------------------
class _StockTags(email_reader._HtmlText):
    """``_HtmlText`` with html.parser's own tag methods: how HTML was read before."""

    parse_starttag = HTMLParser.parse_starttag
    parse_endtag = HTMLParser.parse_endtag


def _stock_text(html: str, monkeypatch: pytest.MonkeyPatch) -> str:
    with monkeypatch.context() as patch:
        patch.setattr(email_reader, "_HtmlText", _StockTags)
        return html_to_text(html)


BROKEN = {
    "stray_angle_brackets": "<p>x</p><<<>>&bogus;",
    "tag_cut_off_at_the_end": "<p>Total</p><a href=\"https://pay.example/",
    "empty_tags": "<body></><p></ ></p><>text<!-- c --><!x><?php echo 1 ?>",
    "greater_than_in_a_value": "<body><a title=\"a > b\" href=x>link</a> after",
    "unclosed_quote": "<body><p>one</p><a href=\"x>two</a><p>three</p>",
}


@pytest.mark.parametrize("name", [*CORPUS, *BROKEN])
def test_html_reads_as_it_does_with_the_stock_tag_methods(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    html = {**CORPUS, **BROKEN}[name]
    assert html_to_text(html) == _stock_text(html, monkeypatch)


@pytest.mark.parametrize("window", [16, 64, 300])
@pytest.mark.parametrize("name", list(BILLS))
def test_tags_longer_than_the_window_read_as_they_do_whole(name: str, window: int,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    # A window of 16 characters is shorter than most tags of these bills: almost every tag is cut.
    stock = _stock_text(BILLS[name], monkeypatch)
    monkeypatch.setattr(email_reader, "MAX_TAG_CHARS", window)
    assert html_to_text(BILLS[name]) == stock == GOLDEN[name]


def _random_html(rng: random.Random) -> str:
    names = ["p", "div", "td", "tr", "table", "a", "b", "span", "br", "img", "li", "h2", "pre", "style", "script"]
    out = ["<body>"]
    for _ in range(rng.randint(5, 40)):
        roll = rng.random()
        if roll < 0.55:
            attrs = []
            for n in range(rng.randint(0, 8)):
                value = rng.choice("xyz") * rng.randint(0, 70)
                attrs.append(rng.choice([f' k{n}="{value}"', f" k{n}='{value}'", f" k{n}={value or 'v'}", f" k{n}"]))
            close = rng.choice([">", ">", " />", "/>"])
            if close == "/>" and attrs and not attrs[-1].endswith(("'", '"')):
                close = " />"  # after a bare value "/>" is part of the value, in the stock parser and here
            out.append(f"<{rng.choice(names)}{''.join(attrs)}{close}")
        elif roll < 0.8:
            out.append(f"</{rng.choice(names)}{rng.choice(['', ' k=v', ' ' * rng.randint(1, 70)])}>")
        elif roll < 0.92:
            out.append(rng.choice(["Total due", "&amp; &lt;b&gt;", "120 kWh", " ", "\n", "$98.10", "a<b"]))
        else:
            out.append(rng.choice(["<!-- c -->", "<!--[if mso]>x<![endif]-->", "<?xml version='1.0'?>",
                                   "<!DOCTYPE html>"]))
    return "".join(out)


@pytest.mark.parametrize("window", [24, 100])
def test_random_markup_reads_as_it_does_with_the_stock_tag_methods(window: int,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    rng = random.Random(20250210)
    documents = [_random_html(rng) for _ in range(300)]
    stock = [_stock_text(html, monkeypatch) for html in documents]
    monkeypatch.setattr(email_reader, "MAX_TAG_CHARS", window)
    for html, expected in zip(documents, stock, strict=True):
        assert html_to_text(html) == expected, html


def test_a_tag_longer_than_the_window_is_the_same_tag_without_its_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    long = 'class="' + "x" * 100 + '"'
    html = (f"<body><p {long}>Total</p><table {long}><tr {long}><td {long}>a</td><td {long}>b</td></tr></table>"
            f"<br {long}/>after<script {long}>if (a < b) document.write('<p>x</p>')</script>end"
            f"<style {long}>td > a {{ color: red }}</style></div {long}>done</body>")
    stock = _stock_text(html, monkeypatch)
    monkeypatch.setattr(email_reader, "MAX_TAG_CHARS", 32)  # each of these tags is longer than that
    assert html_to_text(html) == stock == "Total\na\tb\nafterend\ndone"


def test_a_tag_cut_off_by_the_end_of_the_data_hides_what_it_always_hid(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<body><p>one</p><a " + "b " * 20_000
    assert html_to_text(html) == _stock_text(html, monkeypatch) == "one"


# --- one tag cannot hold the memory ------------------------------------------------------------
# Each is about 1 MB. Before, each peaked at 110 to 180 MB in tracemalloc (the first at 346 MB of
# resident memory in the reviewer's measurement).
SHAPES = {
    # 500,000 attributes: MAX_HTML_CHARS cuts the HTML inside the tag, so the tag never ends.
    "attributes": ("<html><body><a " + "b " * 500_000 + ">x</a></body></html>", ""),
    "unclosed_quote": ("<html><body><a " + 'b="' * 333_000 + "</body></html>", ""),
    "attributes_that_end": ("<html><body><a " + "b " * 450_000 + ">x</a></body></html>", "x"),
    "attributes_with_values": ("<html><body><a " + "b=x " * 220_000 + ">x</a></body></html>", "x"),
    "spaces_in_a_tag": ("<html><body><a" + " " * 900_000 + ">x</a></body></html>", "x"),
    "end_tag_attributes": ("<html><body><p>x</p></p " + "b " * 450_000 + "></body></html>", "x"),
}


@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_tag_of_a_million_characters_takes_little_memory(shape: str) -> None:
    html, text = SHAPES[shape]
    raw = _eml(html)
    assert 850_000 < len(raw) < 1_100_000  # about 1 MB

    tracemalloc.start()
    try:
        package = read_eml(raw)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert (package.body_source, package.body_text) == ("html", text)
    # 100 to 200 times the file before. Now it is what the reader holds of any 1 MB body (the bytes,
    # the parsed part, the decoded text, the copy html.parser works on: about 10 times, and up to
    # 20 for a body that is mostly text).
    assert peak < 20 * len(raw), f"{peak / len(raw):.1f} times the file"


@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_tag_of_a_million_characters_is_read_quickly(shape: str) -> None:
    raw = _eml(SHAPES[shape][0])
    started = time.perf_counter()
    read_eml(raw)
    assert time.perf_counter() - started < budget(1.0)
