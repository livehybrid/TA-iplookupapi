import sys
import splunk.Intersplunk as si
import requests

def get_ip_location(ip):
    response = requests.get(f"https://freeipapi.com/api/json/{ip}", verify=True)
    data = response.json()
    return data

if __name__ == '__main__':
    try:
        keywords,options = si.getKeywordsAndOptions()
        if len(keywords) != 1:
            si.generateErrorResults('Requires fields list.')
            exit(0)
        ip = ''.join(keywords)
        results,dummyresults,settings = si.getOrganizedResults()

        for result in results:
                result.update(get_ip_location(result[ip]))
        si.outputResults(results)
    except Exception as e:
        import traceback
        stack =  traceback.format_exc()
        si.generateErrorResults("Error '%s'. %s" % (e, stack))
